"""Frozen test of known pulse compensation plus RS; preserve all comparisons."""

import argparse
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

from experiment import HERE, REPO, git, json_write, phases, sha
from pulse_v3 import DURATIONS, local_response, readout_response, resource_record, sensing_response
from readout_v2 import protocol_members
from verify_v2_replay import manifest_check


SOURCE_NAMES = ("protocol_v3.json","PULSE_V3_THEORY.md","pulse_v3.py","experiment_v3.py",
                "test_pulse_v3.py","experiment.py","readout_v2.py")


def run(output):
    if output.exists():
        raise FileExistsError("Never overwrite preserved evidence")
    if git("status","--porcelain","--untracked-files=no"):
        raise RuntimeError("Freeze tracked sources before the main experiment")
    for name in SOURCE_NAMES:
        git("ls-files","--error-unmatch",str((HERE/name).relative_to(REPO)))
    manifest_check(HERE/"runs"/"readout_v2")
    cfg = json.loads((HERE/"protocol_v3.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    started = time.perf_counter()
    json_write(output/"provenance.json",{"source_commit":git("rev-parse","HEAD"),
                "sources":{name:sha(HERE/name) for name in SOURCE_NAMES},
                "v2_results_sha256":sha(HERE/"runs"/"readout_v2"/"results.json"),
                "python":sys.version,"numpy":np.__version__,"platform":platform.platform(),
                "utc_started":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                "hardware_calls":0,"paid_calls":0,"independent_investigator":False})
    g = cfg["grid"]
    cycles = g["start"]+(np.arange(g["cells"])+.5)*(g["stop"]-g["start"])/g["cells"]
    errors = np.array([(a,q) for a in cfg["amplitude_errors"] for q in cfg["qubit_detuning_over_reference_omega"]])
    random = cfg["randomized_baseline"]
    members = {name:protocol_members(name,cfg["n"],random["seeds"],random["seed_base"]) for name in cfg["protocols"]}
    resources = [resource_record(w) for w in cfg["waveforms"]]
    if not all(r["within_common_caps"] for r in resources):
        raise ArithmeticError("Resource contract failed")
    summaries = []
    for wave in cfg["waveforms"]:
        rates = {name:np.empty((len(mem),len(errors),len(cycles))) for name,mem in members.items()}
        leaks = {name:np.empty((len(errors),len(cycles))) for name in members}
        for e,error in enumerate(errors):
            args = dict(eta=cfg["eta"],amplitude_error=float(error[0]),qubit_detuning=float(error[1])*4*np.pi)
            local = local_response(wave,cycles,slices=cfg["integration_slices"],**args)
            for name,mem in members.items():
                leakage = []
                for m,phase in enumerate(mem):
                    u,du = sensing_response(wave,phase,cycles,local,args["qubit_detuning"])
                    rate,p,dp = readout_response(u,du,cycles,n=cfg["n"],**args)
                    rates[name][m,e] = rate
                    leakage.append(np.sum(np.abs(u[:,2,:2])**2,axis=1))
                leaks[name][e] = np.mean(leakage,axis=0)
            print(json.dumps({"stage":"screen","waveform":wave,"error_pairs_complete":e+1}),flush=True)
        for name,member_rates in rates.items():
            score = member_rates.mean(axis=0)
            worst = np.unravel_index(np.argmin(score),score.shape)
            row = {"waveform":wave,"sequence":name,"id":f"{wave}/{name}",
                   "minimum_rate":float(score.min()),"median_rate":float(np.median(score)),
                   "maximum_rate":float(score.max()),"max_mean_worst_input_leakage":float(leaks[name].max()),
                   "phase_realizations":len(members[name]),"worst_cycles":float(cycles[worst[1]]),
                   "worst_errors":errors[worst[0]].tolist()}
            if len(members[name])>1:
                row["seed_standard_error_at_worst_point"] = float(member_rates[:,worst[0],worst[1]].std(ddof=1)/np.sqrt(len(members[name])))
            summaries.append(row)
            np.savez_compressed(output/f"screen_{wave}_{name}.npz",cycles=cycles,errors=errors,
                                fi_rate=score,member_fi_rate=member_rates,mean_worst_input_leakage=leaks[name],
                                phase_members=np.array(members[name]))
            print(json.dumps({"stage":"summary",**row}),flush=True)
    conv = cfg["convergence"]
    convergence = []
    args = dict(eta=cfg["eta"],amplitude_error=conv["error_pair"][0],qubit_detuning=conv["error_pair"][1]*4*np.pi)
    for wave in ("HANN","DRAG3"):
        for name in conv["sequences"]:
            history = []
            for slices in conv["slices"]:
                local = local_response(wave,conv["cycles"],slices=slices,**args)
                u,du = sensing_response(wave,phases(name,cfg["n"]),conv["cycles"],local,args["qubit_detuning"])
                history.append(readout_response(u,du,conv["cycles"],n=cfg["n"],**args)[0])
            history = np.array(history)
            passed = bool(np.allclose(history[-1],history[-2],rtol=conv["rtol"],atol=conv["atol"]))
            convergence.append({"id":f"{wave}/{name}","pass":passed,
                                "max_relative_128_256_difference":float(np.max(np.abs(history[-1]-history[-2])/np.maximum(history[-1],1e-15)))})
            np.savez_compressed(output/f"convergence_{wave}_{name}.npz",cycles=conv["cycles"],slices=conv["slices"],rates=history)
    candidate = next(s for s in summaries if s["id"]==cfg["candidate"])
    baselines = [s for s in summaries if s["sequence"] not in ("RS_prefix","raw_RS")]
    best_min = max(baselines,key=lambda r:r["minimum_rate"])
    best_med = max(baselines,key=lambda r:r["median_rate"])
    ratio_min,ratio_med = candidate["minimum_rate"]/best_min["minimum_rate"],candidate["median_rate"]/best_med["median_rate"]
    numeric = all(r["pass"] for r in convergence)
    advantage = ratio_min>=2 and ratio_med>=.9 and numeric
    result = {"protocol_id":cfg["id"],"screen":summaries,"resources":resources,
              "points_per_combination":len(cycles)*len(errors),"combinations":len(summaries),
              "candidate":candidate["id"],"best_minimum_baseline":best_min["id"],"best_median_baseline":best_med["id"],
              "candidate_to_best_minimum_ratio":ratio_min,"candidate_to_best_median_ratio":ratio_med,
              "convergence":convergence,"numerical_gate_pass":numeric,"advantage_gate_pass":advantage,
              "decision":"LOCAL_COMBINATION_ADVANTAGE_NOT_NOVELTY_ADMITTED" if advantage else ("NO_QUALIFYING_COMBINATION_ADVANTAGE" if numeric else "NUMERICAL_GATE_UNRESOLVED"),
              "continuous_domain_certified":False,"novelty":"NOT_ADMITTED_KNOWN_CONTROL_FOUNDATION",
              "hardware_validation":"NOT_TESTED","mass_enterprise_validation":"NOT_TESTED",
              "mission_complete":False,"seconds":time.perf_counter()-started}
    json_write(output/"results.json",result)
    json_write(output/"checksums.json",{p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    print(json.dumps({k:v for k,v in result.items() if k!="screen"},indent=2),flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    run(parser.parse_args().output.resolve())
