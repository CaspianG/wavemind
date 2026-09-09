"""Implementation controls; no assertions of novelty or candidate success."""

import numpy as np

from experiment import Z, phases, propagate, unitary
from pulse_v3 import (DELTA_REF, DURATIONS, control_hamiltonian, local_response,
                      readout_response, resource_record, sensing_response, waveform)
from readout_v2 import native_statistics, protocol_members


def test_waveform_boundaries_area_and_common_resource_caps():
    t = np.linspace(0,.25,16385)
    x,y,d = waveform("HANN",t)
    assert np.isclose(np.trapezoid(x,t),np.pi,rtol=1e-12)
    assert np.isclose(np.trapezoid(x*x,t),6*np.pi**2,rtol=1e-12)
    for name in DURATIONS:
        assert resource_record(name)["within_common_caps"]
    for values in waveform("DRAG3",np.array([0.,.25])):
        np.testing.assert_allclose(values,0,atol=1e-12)
    assert np.sqrt((8*np.pi)**2+(32*np.pi**2/DELTA_REF)**2)<8.1*np.pi
    assert 6*np.pi**2+((32*np.pi**2)**2*.25/2)/DELTA_REF**2<8*np.pi**2


def test_additional_longitudinal_control_shifts_the_spectator_too():
    h = control_hamiltonian([80.],3.,4.,-2.,eta=1.2,amplitude_error=.02,qubit_detuning=.4)[0]
    np.testing.assert_allclose(np.diag(h),[.2,-2.2,76.])
    np.testing.assert_allclose(h,h.conj().T)
    assert h[0,1] == 1.02*(3-4j)/2
    assert np.isclose(h[1,2],1.2*h[0,1])


def test_phase_covariance_matches_rectangular_propagator():
    phase = protocol_members("RXY8",16,seeds=1)[0]
    args = dict(eta=1.,amplitude_error=.02,qubit_detuning=-.02*4*np.pi)
    cycles = np.array([12.001953125,14.001953125,15.998046875])
    for name,tp in (("RECT",.25),("FAST_RECT",.125)):
        local = local_response(name,cycles,**args)
        u,du = sensing_response(name,phase,cycles,local,args["qubit_detuning"])
        expected,dexpected = propagate(phase,2*np.pi*cycles,tp=tp,derivative="signal",**args)
        np.testing.assert_allclose(u,expected,rtol=1e-10,atol=1e-11)
        np.testing.assert_allclose(du,dexpected,rtol=1e-9,atol=1e-10)


def test_rectangular_full_native_readout_matches_v2():
    cycles,phase = np.array([12.12,14.14]),phases("RS_prefix",16)
    args = dict(eta=1.,amplitude_error=-.02,qubit_detuning=.02*4*np.pi)
    u,du = sensing_response("RECT",phase,cycles,local_response("RECT",cycles,**args),args["qubit_detuning"])
    actual = readout_response(u,du,cycles,n=16,**args)
    expected = native_statistics(phase,cycles,**args)
    for a,b in zip(actual,expected):
        np.testing.assert_allclose(a,b,rtol=1e-9,atol=1e-11)


def test_shaped_signal_derivative_against_finite_signal():
    cycles = np.array([12.125,14.125])
    slices,dt,start = 256,.25/256,.375
    u,du = local_response("DRAG3",cycles,slices=slices)
    x,y,d = waveform("DRAG3",(np.arange(slices)+.5)*dt)
    eps,finite = 1e-5,[]
    for b in (eps,-eps):
        current = np.broadcast_to(np.eye(3,dtype=complex),(2,3,3)).copy()
        for k in range(slices):
            h = control_hamiltonian(2*np.pi*cycles,x[k],y[k],d[k])
            step = unitary(h+b*np.cos(np.pi*(start+(k+.5)*dt))*Z/2,dt)
            current = step@current
        finite.append(current)
    np.testing.assert_allclose((finite[0]-finite[1])/(2*eps),du,rtol=1e-4,atol=2e-7)
    np.testing.assert_allclose(u@u.conj().swapaxes(-1,-2),np.broadcast_to(np.eye(3),(2,3,3)),atol=1e-11)


def test_new_midpoint_grid_is_disjoint_from_v2_grid():
    original = np.linspace(12.,16.,1025)
    new = 12+(np.arange(1024)+.5)*4/1024
    assert np.intersect1d(original,new).size == 0
    assert new[0]>12 and new[-1]<16  # no continuous-boundary claim.
