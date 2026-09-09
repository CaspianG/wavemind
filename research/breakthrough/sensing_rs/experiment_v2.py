"""Frozen follow-up: finite native readout, equal-budget baselines and covers."""

import argparse
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

from experiment import HERE, REPO, git, grid, json_write, phases, sha
from off_grid_audit import check_evidence
from readout_v2 import (SETTINGS, analysis_segments, continuous_audit,
                        dephasing_statistics, native_statistics, protocol_members)


SOURCE_NAMES = ("protocol_v2.json", "READOUT_V2_THEORY.md", "readout_v2.py",
                "experiment_v2.py", "test_readout_v2.py", "experiment.py")


def run(output):
    if output.exists():
        raise FileExistsError("Output directory must not exist")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("Commit tracked changes before executing frozen protocol")
    for name in SOURCE_NAMES:
        git("ls-files", "--error-unmatch", str((HERE/name).relative_to(REPO)))
    old_source = check_evidence(HERE/"runs"/"v1")
    cfg = json.loads((HERE/"protocol_v2.json").read_text(encoding="utf-8"))
    old_roots = json.loads((HERE/"runs"/"off_grid_v1"/"results.json").read_text(encoding="utf-8"))["roots"]
    output.mkdir(parents=True)
    started = time.perf_counter()
    json_write(output/"provenance.json", {"source_commit":git("rev-parse","HEAD"),
               "sources":{name:sha(HERE/name) for name in SOURCE_NAMES},
               "original_source_commit":old_source["source_commit"],
               "old_roots_sha256":sha(HERE/"runs"/"off_grid_v1"/"results.json"),
               "python":sys.version,"numpy":np.__version__,"platform":platform.platform(),
               "utc_started":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
               "independent_investigator":False,"hardware_calls":0})
    cycles = grid(cfg["grid"])
    errors = np.array([(a,q) for a in cfg["amplitude_errors"] for q in cfg["qubit_detuning_over_omega"]])
    detector = cfg["readout"]
    options = dict(eta=cfg["eta"],tp=cfg["tp"],exponent=cfg["noise"]["primary_depolarizing_exponent"],
                   p_bright=detector["p_bright"],p_dark=detector["p_dark"],overhead=cfg["overhead"])

    def evaluate(phase,points,error,**overrides):
        args = {**options,**overrides}
        return native_statistics(phase,points,amplitude_error=float(error[0]),
                                  qubit_detuning=float(error[1])*np.pi/cfg["tp"],**args)

    summaries = []
    candidate_slopes = None
    randomized = cfg["randomized_baseline"]
    for name in cfg["protocols"]:
        members = protocol_members(name,cfg["n"],randomized["seeds"],randomized["seed_base"])
        member_rates = []
        member_p = member_dp = None
        for index,phase in enumerate(members):
            rates,ps,dps = [],[],[]
            for error in errors:
                rate,p,dp = evaluate(phase,cycles,error)
                rates.append(rate); ps.append(p); dps.append(dp)
            member_rates.append(rates)
            if len(members)==1:
                member_p,member_dp = np.array(ps),np.array(dps)
            if name=="RXY8" and (index+1)%8==0:
                print(json.dumps({"stage":"randomized_baseline","members_done":index+1}),flush=True)
        member_rates = np.array(member_rates)
        rates = member_rates.mean(axis=0)
        worst = np.unravel_index(np.argmin(rates),rates.shape)
        summary = {"protocol":name,"phase_realizations":len(members),
                   "minimum_rate":float(rates.min()),"median_rate":float(np.median(rates)),
                   "maximum_rate":float(rates.max()),
                   "worst_point":{"amplitude_error":float(errors[worst[0],0]),
                                  "qubit_detuning_over_omega":float(errors[worst[0],1]),
                                  "spectator_cycles":float(cycles[worst[1]])}}
        if len(members)>1:
            summary["seed_standard_error_at_worst_point"] = float(member_rates[:,worst[0],worst[1]].std(ddof=1)/np.sqrt(len(members)))
        summaries.append(summary)
        payload = dict(cycles=cycles,errors=errors,fi_rate=rates,member_fi_rates=member_rates,
                       phase_realizations=np.array(members))
        if member_p is not None:
            payload.update(click_probability=member_p,dp_db=member_dp)
        np.savez_compressed(output/f"screen_{name}.npz",**payload)
        if name=="RS_prefix":
            candidate_slopes = member_dp
        print(json.dumps({"stage":"screen",**summary}),flush=True)

    ideal_rate = float(evaluate(phases("CP",cfg["n"]),np.array([0.]),[0,0],eta=0.)[0][0])
    blind_checks = []
    for old in old_roots:
        cycle = old["root_approximation"]["cycles"]
        rate,p,dp = evaluate(phases("RS_prefix",cfg["n"]),np.array([cycle]),old["error_setting"])
        blind_checks.append({"cycles":cycle,"errors":old["error_setting"],"rate":float(rate[0]),
                             "fraction_of_ideal_rate":float(rate[0]/ideal_rate),
                             "click_probabilities":p[0].tolist(),"slopes":dp[0].tolist()})
    blind_ok = all(row["fraction_of_ideal_rate"]>=.01 for row in blind_checks)
    print(json.dumps({"stage":"old_blind_spots","minimum_fraction_of_ideal":min(r["fraction_of_ideal_rate"] for r in blind_checks),
                      "gate_pass":blind_ok}),flush=True)

    cover_results = []
    for index,error in enumerate(errors):
        callback = lambda points: evaluate(phases("RS_prefix",cfg["n"]),points,error)[2]
        audit,cells,unresolved = continuous_audit(cycles,candidate_slopes[index],callback,
                    maximum_points=cfg["continuous_audit"]["maximum_points_per_error_pair"],
                    endpoint_error=cfg["continuous_audit"]["endpoint_slope_vector_error_allowance"],
                    n=cfg["n"],**{k:v for k,v in options.items() if k!="eta"})
        audit["errors"] = error.tolist()
        cover_results.append(audit)
        np.savez_compressed(output/f"cover_{index}.npz",accepted_intervals=cells,unresolved_intervals=unresolved)
        print(json.dumps({"stage":"continuous_cover",**audit}),flush=True)

    stress = cfg["dephasing_stress"]
    cases = [(r["root_approximation"]["cycles"],*r["error_setting"]) for r in old_roots]
    cases += [(x,a,0.) for a in (-.02,0.,.02) for x in (12.,12.125,12.25,13.,14.,15.,16.)]
    cases = np.array(cases)
    stress_results = []
    for name in stress["protocols"]:
        histories = []
        diagnostics = []
        for slices in stress["pulse_slices"]:
            rates = np.zeros(len(cases))
            for error in np.unique(cases[:,1:],axis=0):
                mask = np.all(cases[:,1:]==error,axis=1)
                values,p,dp,diagnostic = dephasing_statistics(phases(name,cfg["n"]),cases[mask,0],
                        amplitude_error=float(error[0]),qubit_detuning=float(error[1])*np.pi/cfg["tp"],
                        eta=cfg["eta"],tp=cfg["tp"],exponent=stress["gamma_times_total_duration"],slices=slices,
                        p_bright=detector["p_bright"],p_dark=detector["p_dark"],overhead=cfg["overhead"])
                rates[mask] = values
                diagnostics.append(diagnostic)
            histories.append(rates)
            print(json.dumps({"stage":"dephasing","protocol":name,"slices":slices,"minimum_rate":float(rates.min())}),flush=True)
        histories = np.array(histories)
        converged = np.allclose(histories[-1],histories[-2],rtol=stress["convergence_relative_tolerance"],
                                atol=stress["convergence_absolute_tolerance"])
        stress_results.append({"protocol":name,"cases":len(cases),"converged":bool(converged),
                               "minimum_rate":float(histories[-1].min()),"median_rate":float(np.median(histories[-1])),
                               "max_trace_error":max(d["trace_error"] for d in diagnostics),
                               "minimum_density_eigenvalue":min(d["minimum_eigenvalue"] for d in diagnostics)})
        np.savez_compressed(output/f"dephasing_{name}.npz",cases=cases,slices=np.array(stress["pulse_slices"]),rates=histories)

    candidate = summaries[0]
    baselines = [r for r in summaries if r["protocol"] not in ("RS_prefix","raw_RS")]
    best_min = max(baselines,key=lambda r:r["minimum_rate"])
    best_median = max(baselines,key=lambda r:r["median_rate"])
    minimum_ratio = candidate["minimum_rate"]/best_min["minimum_rate"]
    median_ratio = candidate["median_rate"]/best_median["median_rate"]
    advantage = minimum_ratio>=2 and median_ratio>=.9
    result = {"protocol_id":cfg["id"],"screen":summaries,"points_per_protocol":len(errors)*len(cycles),
              "ideal_cp_rate_same_noise_and_detector":ideal_rate,"old_blind_spots":blind_checks,
              "old_blind_spot_gate_pass":blind_ok,"continuous_covers":cover_results,
              "conditional_continuous_covers_complete":all(r["conditional_cover_complete"] for r in cover_results),
              "best_minimum_baseline":best_min["protocol"],"best_median_baseline":best_median["protocol"],
              "candidate_to_best_minimum_ratio":minimum_ratio,"candidate_to_best_median_ratio":median_ratio,
              "advantage_gate_pass":advantage,"dephasing_stress":stress_results,
              "decision":"LOCAL_UPGRADE_NOT_NOVELTY_ADMITTED" if advantage and blind_ok else "READOUT_UPGRADE_NO_QUALIFYING_ADVANTAGE",
              "novelty":"UNKNOWN","hardware_validation":"NOT_TESTED","mass_enterprise_validation":"NOT_TESTED",
              "mission_complete":False,"seconds":time.perf_counter()-started}
    json_write(output/"results.json",result)
    # A dimensionless schedule is a simulation/review artifact, not a device command.
    schedule = {"units":"tau=1, phase in radians; no hardware frequency/calibration supplied",
                "protocol":"RS_prefix","n":cfg["n"],"preparation":"ideal plus_x assumption",
                "sensing_pulses":[{"center":j+.5,"duration":cfg["tp"],"phase":float(phi)}
                                   for j,phi in enumerate(phases("RS_prefix",cfg["n"]))],
                "analysis_settings":{s:[{"start":a,"duration":b,"phase":None if c is None else float(c)}
                                          for a,b,c in analysis_segments(s,cfg["n"],cfg["tp"])] for s in SETTINGS},
                "native_detector":detector,"simulation_only":True}
    json_write(output/"schedule.json",schedule)
    json_write(output/"checksums.json",{p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    print(json.dumps({k:v for k,v in result.items() if k not in ("screen","old_blind_spots","continuous_covers")},indent=2),flush=True)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    run(parser.parse_args().output.resolve())
