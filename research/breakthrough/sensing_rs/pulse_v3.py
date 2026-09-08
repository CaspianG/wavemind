"""Fixed pulse-local compensation, including its additional control cost."""

import numpy as np

from experiment import PLUS_X, Z, pulse_response
from readout_v2 import SETTINGS, analysis_segments, segment_response


DURATIONS = {"RECT":.25, "FAST_RECT":.125, "HANN":.25, "DRAG3":.25}
DELTA_REF = 28*np.pi


def waveform(name, u):
    tp = DURATIONS[name]
    u = np.asarray(u, dtype=float)
    if name in ("RECT", "FAST_RECT"):
        return np.full_like(u, np.pi/tp), np.zeros_like(u), np.zeros_like(u)
    a = np.pi/tp*(1-np.cos(2*np.pi*u/tp))
    da = 2*np.pi**2/tp**2*np.sin(2*np.pi*u/tp)
    if name == "HANN":
        return a, np.zeros_like(u), np.zeros_like(u)
    return a-3*a**3/(8*DELTA_REF**2), -da/DELTA_REF, -3*a**2/(4*DELTA_REF)


def control_hamiltonian(delta, x, y, longitudinal, eta=1., amplitude_error=0., qubit_detuning=0.):
    delta = np.atleast_1d(delta)
    h = np.zeros((len(delta),3,3), dtype=complex)
    h[:,0,0], h[:,1,1], h[:,2,2] = qubit_detuning/2, -qubit_detuning/2+longitudinal, delta+2*longitudinal
    drive = (1+amplitude_error)*(x-1j*y)/2
    h[:,0,1] = h[:,1,2] = drive
    h[:,1,2] *= eta
    h[:,1,0], h[:,2,1] = h[:,0,1].conj(), h[:,1,2].conj()
    return h


def local_response(name, cycles, slices=128, eta=1., amplitude_error=0., qubit_detuning=0.):
    delta = 2*np.pi*np.atleast_1d(cycles)
    tp = DURATIONS[name]
    count = 1 if name in ("RECT", "FAST_RECT") else slices
    dt, start = tp/count, (1-tp)/2
    u = np.broadcast_to(np.eye(3, dtype=complex), (len(delta),3,3)).copy()
    du = np.zeros_like(u)
    x,y,d = waveform(name, (np.arange(count)+.5)*dt)
    for k in range(count):
        h = control_hamiltonian(delta, x[k], y[k], d[k], eta, amplitude_error, qubit_detuning)
        step, dstep = pulse_response(h, Z/2, dt, np.pi, start+k*dt)
        du, u = step@du+dstep@u, step@u
    return u, du


def sensing_response(name, pulse_phases, cycles, local, qubit_detuning=0.):
    delta = 2*np.pi*np.atleast_1d(cycles)
    tp, n = DURATIONS[name], len(pulse_phases)
    g = (1-tp)/2
    energies = np.column_stack((np.full(len(delta),qubit_detuning/2), np.full(len(delta),-qubit_detuning/2), delta))
    u = np.broadcast_to(np.eye(3, dtype=complex), (len(delta),3,3)).copy()
    du = np.zeros_like(u)

    def idle(current, derivative, start, length):
        diag = np.exp(-1j*energies*length)
        integral = (np.sin(np.pi*(start+length))-np.sin(np.pi*start))/np.pi
        ddiag = -.5j*integral*np.diag(Z)*diag
        return diag[:,:,None]*current, diag[:,:,None]*derivative+ddiag[:,:,None]*current

    u,du = idle(u,du,0,g)
    cached = {}
    for phi in np.unique(pulse_phases):
        d = np.exp(1j*np.array([-phi,0.,phi]))
        factor = d[:,None]*d.conj()[None,:]
        cached[float(phi)] = (local[0]*factor, local[1]*factor)
    for j, phi in enumerate(pulse_phases):
        step,dstep = cached[float(phi)]
        du,u = step@du+(-1)**j*dstep@u, step@u
        u,du = idle(u,du,g+j+tp,g if j==n-1 else 1-tp)
    return u,du


def readout_response(u, du, cycles, n=64, eta=1., amplitude_error=0., qubit_detuning=0.,
                     exponent=.2, p_bright=.10, p_dark=.07, overhead=10.):
    psi0,dpsi0 = u@PLUS_X, du@PLUS_X
    delta, visibility = 2*np.pi*np.atleast_1d(cycles), np.exp(-exponent)
    probabilities, slopes = [],[]
    for setting in SETTINGS:
        psi,dpsi = psi0.copy(),dpsi0.copy()
        for start,length,phi in analysis_segments(setting,n,.25):
            if length == 0:
                continue
            step,dstep = segment_response(delta,start,length,phi,eta,amplitude_error,qubit_detuning,.25)
            dpsi,psi = (step@dpsi[...,None]+dstep@psi[...,None])[...,0], (step@psi[...,None])[...,0]
        if np.max(np.abs(np.sum(np.abs(psi)**2,axis=1)-1)) > 2e-9:
            raise ArithmeticError("State norm lost")
        p0 = visibility*np.abs(psi[:,0])**2+(1-visibility)/3
        dp0 = visibility*2*np.real(psi[:,0].conj()*dpsi[:,0])
        probabilities.append(p_dark+(p_bright-p_dark)*p0)
        slopes.append((p_bright-p_dark)*dp0)
    p,dp = np.array(probabilities).T,np.array(slopes).T
    if not np.all(np.isfinite(p)) or not np.all(np.isfinite(dp)) or np.any((p<=0)|(p>=1)):
        raise ArithmeticError("Invalid Bernoulli statistics")
    return np.mean(dp**2/(p*(1-p)),axis=1)/(n+.25+overhead),p,dp


def resource_record(name):
    tp = DURATIONS[name]
    t = np.linspace(0,tp,16385)
    x,y,d = waveform(name,t)
    peak = float(np.max(np.hypot(x,y)))
    energy = float(np.trapezoid(x*x+y*y,t))
    long_peak = float(np.max(np.abs(d)))
    return {"waveform":name,"duration":tp,"nominal_rf_peak":peak,"nominal_rf_energy":energy,
            "nominal_longitudinal_peak":long_peak,
            "nominal_longitudinal_energy":float(np.trapezoid(d*d,t)),
            "within_common_caps":bool(peak<=8.1*np.pi+1e-12 and energy<=8*np.pi**2+1e-10 and long_peak<=6)}
