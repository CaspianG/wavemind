"""Native finite-pulse readout; no ideal qutrit measurement or postselection."""

import math

import numpy as np

from experiment import PLUS_X, Z, hamiltonian, phases, propagate, pulse_response


SETTINGS = ("Z+", "Z-", "X+", "X-", "Y+", "Y-")
ANGLES = np.pi*np.array([0, 1, .5, .5, .5, .5])
PHASES = np.pi*np.array([0, 0, 1.5, .5, 0, 1])


def protocol_members(name, n, seeds=32, seed_base=260908):
    if name != "RXY8":
        return [phases(name, n)]
    if n % 8:
        raise ValueError("RXY8 requires complete XY8 blocks")
    return [phases("XY8", n)+np.repeat(np.random.Generator(np.random.PCG64(seed_base+i))
                                      .uniform(0, 2*np.pi, n//8), 8) for i in range(seeds)]


def analysis_segments(setting, start, tp=.25):
    index = SETTINGS.index(setting)
    duration = ANGLES[index]/(np.pi/tp)
    pad = (tp-duration)/2
    return [(start, pad, None), (start+pad, duration, PHASES[index]),
            (start+pad+duration, pad, None)]


def segment_response(delta, start, duration, phi, eta, amplitude_error, qubit_detuning, tp):
    h, _ = hamiltonian(delta, 0 if phi is None else phi, eta,
                       0 if phi is None else np.pi/tp, amplitude_error, qubit_detuning)
    return pulse_response(h, Z/2, duration, np.pi, start)


def native_statistics(pulse_phases, cycles, eta=1., amplitude_error=0., qubit_detuning=0.,
                      tp=.25, exponent=.2, p_bright=.10, p_dark=.07, overhead=10.):
    if not 0 < p_dark < p_bright < .5 or exponent < 0:
        raise ValueError("Require 0 < p_dark < p_bright < 0.5 and nonnegative noise")
    delta = 2*np.pi*np.atleast_1d(cycles)
    u, du = propagate(pulse_phases, delta, eta, tp=tp, amplitude_error=amplitude_error,
                      qubit_detuning=qubit_detuning, derivative="signal")
    psi0, dpsi0 = u @ PLUS_X, du @ PLUS_X
    p, dp = [], []
    visibility = np.exp(-exponent)
    for setting in SETTINGS:
        psi, dpsi = psi0.copy(), dpsi0.copy()
        for start, duration, phi in analysis_segments(setting, len(pulse_phases), tp):
            if duration == 0:
                continue
            step, dstep = segment_response(delta, start, duration, phi, eta,
                                           amplitude_error, qubit_detuning, tp)
            dpsi = (step @ dpsi[..., None] + dstep @ psi[..., None])[..., 0]
            psi = (step @ psi[..., None])[..., 0]
        if np.max(np.abs(np.sum(np.abs(psi)**2, axis=-1)-1)) > 1e-10:
            raise ArithmeticError("State norm lost")
        population = visibility*np.abs(psi[:,0])**2+(1-visibility)/3
        derivative = visibility*2*np.real(psi[:,0].conj()*dpsi[:,0])
        p.append(p_dark+(p_bright-p_dark)*population)
        dp.append((p_bright-p_dark)*derivative)
    p, dp = np.array(p).T, np.array(dp).T
    rates = np.mean(dp**2/(p*(1-p)), axis=1)/(len(pulse_phases)+tp+overhead)
    return rates, p, dp


def ideal_frame_statistics(rho, derivative, p_bright=.10, p_dark=.07):
    """Ideal comparison ONLY: six embedded qubit projectors, not qutrit IC."""
    vectors = [np.array(v, complex) for v in
               ([1,0,0], [0,1,0], [1,1,0], [1,-1,0], [1,1j,0], [1,-1j,0])]
    vectors = [v/np.linalg.norm(v) for v in vectors]
    c = p_bright-p_dark
    p = np.array([p_dark+c*np.real(v.conj() @ rho @ v) for v in vectors])
    dp = np.array([c*np.real(v.conj() @ derivative @ v) for v in vectors])
    return p, dp


def curvature_bound(n=64, tp=.25, exponent=.2, p_bright=.10, p_dark=.07):
    total = n+tp
    # Here 0<tp<=0.5 and n is an even integer: integrate |cos(pi*t)| exactly.
    if not 0 < tp <= .5 or n % 2:
        raise ValueError("Curvature bound integral implemented for even N, 0<tp<=0.5")
    b_integral = n/np.pi + np.sin(np.pi*tp)/(2*np.pi)
    return np.sqrt(6)*(p_bright-p_dark)*np.exp(-exponent)*8*(np.pi*total)**2*b_integral


def interpolation_lower(left_vectors, right_vectors, widths, curvature, endpoint_error):
    difference = right_vectors-left_vectors
    denominator = np.sum(difference**2, axis=-1)
    numerator = -np.sum(left_vectors*difference, axis=-1)
    alpha = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator>0)
    alpha = np.clip(alpha, 0, 1)
    chord_minimum = np.linalg.norm(left_vectors+alpha[...,None]*difference, axis=-1)
    return np.maximum(0, chord_minimum-curvature*np.asarray(widths)**2/8-endpoint_error)


def continuous_audit(cycles, slopes, evaluate, maximum_points=32769, endpoint_error=1e-7,
                     n=64, tp=.25, exponent=.2, p_bright=.10, p_dark=.07, overhead=10.):
    """Cover a whole detuning interval; never omit failed/budget-limited cells."""
    lo, hi = cycles[:-1].copy(), cycles[1:].copy()
    vl, vr = slopes[:-1].copy(), slopes[1:].copy()
    used = len(cycles)
    accepted = []
    curvature = curvature_bound(n,tp,exponent,p_bright,p_dark)
    rounds = 0
    while len(lo):
        lower = interpolation_lower(vl,vr,hi-lo,curvature,endpoint_error)
        good = lower > 0
        if np.any(good):
            accepted.append(np.column_stack((lo[good],hi[good],lower[good])))
        lo,hi,vl,vr = lo[~good],hi[~good],vl[~good],vr[~good]
        if not len(lo) or used+len(lo)>maximum_points:
            break
        middle = (lo+hi)/2
        vm = evaluate(middle)
        used += len(middle)
        lo,hi,vl,vr = (np.concatenate((lo,middle)),np.concatenate((middle,hi)),
                       np.concatenate((vl,vm)),np.concatenate((vm,vr)))
        rounds += 1
    cells = np.concatenate(accepted) if accepted else np.zeros((0,3))
    if len(cells):
        cells = cells[np.argsort(cells[:,0])]
    unresolved = np.column_stack((lo,hi)) if len(lo) else np.zeros((0,2))
    minimum = float(cells[:,2].min()) if len(cells) and not len(lo) else 0.
    result = {"conditional_cover_complete": not bool(len(lo)), "evaluated_points": used,
              "refinement_rounds": rounds, "accepted_intervals": len(cells),
              "unresolved_intervals": len(lo), "curvature_bound": float(curvature),
              "endpoint_error_allowance": endpoint_error,
              "conditional_minimum_fi_rate": minimum**2/(6*p_bright*(1-p_bright)*(n+tp+overhead)),
              "interval_arithmetic_certified": False}
    return result,cells,unresolved


def dephasing_statistics(pulse_phases, cycles, amplitude_error=0., qubit_detuning=0.,
                        eta=1., tp=.25, exponent=.2, slices=64,
                        p_bright=.10, p_dark=.07, overhead=10.):
    """CP Strang splitting for phase damping; independent noise-model stress.

    gamma is chosen so bare qubit coherence decays by exp(-exponent) over
    total sensing+analysis time. Includes exact weak-signal action per
    unitary substep and commuting phase damping during every idle segment.
    """
    delta = 2*np.pi*np.atleast_1d(cycles)
    n = len(pulse_phases)
    gamma = exponent/(n+tp)
    rho = np.broadcast_to(np.outer(PLUS_X,PLUS_X.conj()), (len(delta),3,3)).copy()
    drho = np.zeros_like(rho)
    eigen_z = np.real(np.diag(Z))
    zdiff = eigen_z[:,None]-eigen_z[None,:]
    energies = np.column_stack((np.full(len(delta),qubit_detuning/2),
                                np.full(len(delta),-qubit_detuning/2),delta))
    ediff = energies[:,:,None]-energies[:,None,:]

    def free(r,d,start,length):
        factor = np.exp(-1j*ediff*length-gamma*zdiff**2*length/4)
        integral = (np.sin(np.pi*(start+length))-np.sin(np.pi*start))/np.pi
        return factor*r, factor*(d-1j*integral*zdiff*r/2)

    def rotate(r,d,u,du,damping):
        r,d = damping*r,damping*d
        adj = u.conj().swapaxes(-1,-2)
        rnext = u @ r @ adj
        dnext = u @ d @ adj + du @ r @ adj + u @ r @ du.conj().swapaxes(-1,-2)
        return damping*rnext,damping*dnext

    dt = tp/slices
    damping = np.exp(-gamma*zdiff**2*dt/8)
    g = (1-tp)/2
    cache = {}
    for phi in np.unique(pulse_phases):
        cache[float(phi)] = [segment_response(delta,g+k*dt,dt,float(phi),eta,
                                               amplitude_error,qubit_detuning,tp) for k in range(slices)]
    rho,drho = free(rho,drho,0,g)
    for j,phi in enumerate(pulse_phases):
        for u,du in cache[float(phi)]:
            rho,drho = rotate(rho,drho,u,(-1)**j*du,damping)
        rho,drho = free(rho,drho,g+j+tp,g if j==n-1 else 1-tp)
    p,dp = [],[]
    worst_trace = worst_negative = 0.
    for setting in SETTINGS:
        r,d = rho.copy(),drho.copy()
        for start,length,phi in analysis_segments(setting,n,tp):
            if length==0:
                continue
            if phi is None:
                r,d = free(r,d,start,length)
            else:
                count = max(1,int(round(slices*length/tp)))
                step_length = length/count
                damp = np.exp(-gamma*zdiff**2*step_length/8)
                for k in range(count):
                    u,du = segment_response(delta,start+k*step_length,step_length,phi,
                                            eta,amplitude_error,qubit_detuning,tp)
                    r,d = rotate(r,d,u,du,damp)
        worst_trace = max(worst_trace,float(np.max(np.abs(np.trace(r,axis1=-2,axis2=-1)-1))),
                          float(np.max(np.abs(np.trace(d,axis1=-2,axis2=-1)))))
        worst_negative = min(worst_negative,float(np.linalg.eigvalsh(r).min()))
        p.append(p_dark+(p_bright-p_dark)*r[:,0,0].real)
        dp.append((p_bright-p_dark)*d[:,0,0].real)
    if worst_trace>1e-7 or worst_negative < -1e-9:
        raise ArithmeticError("Density matrix or its derivative failed physicality checks")
    p,dp = np.array(p).T,np.array(dp).T
    rates = np.mean(dp**2/(p*(1-p)),axis=1)/(n+tp+overhead)
    return rates,p,dp,{"trace_error":worst_trace,"minimum_eigenvalue":worst_negative}
