"""Tests for new readout/coverage code, not tests of scientific priority."""

import numpy as np

from experiment import PLUS_X, Z, finite_signal, phases, propagate, pulse_response, unitary
from readout_v2 import (SETTINGS, analysis_segments, continuous_audit, curvature_bound,
                        dephasing_statistics, ideal_frame_statistics, interpolation_lower,
                        native_statistics, protocol_members, segment_response)


def test_common_budget_and_deterministic_randomized_protocol():
    for setting in SETTINGS:
        segments = analysis_segments(setting,64)
        assert abs(sum(t for _,t,_ in segments)-.25)<1e-15
        assert segments[0][0]==64
        assert abs(segments[-1][0]+segments[-1][1]-64.25)<1e-15
    members = protocol_members("RXY8",64)
    assert len(members)==32
    assert np.array_equal(members[7],protocol_members("RXY8",64)[7])
    assert not np.array_equal(members[0],members[1])
    difference = (members[0]-phases("XY8",64)).reshape(8,8)
    assert np.max(np.ptp(difference,axis=1))<1e-14


def test_ideal_frame_identity_and_missing_leakage_coherence():
    rho = np.eye(3)/3
    derivative = np.array([[.2,.3+.4j,0],[.3-.4j,-.1,0],[0,0,-.1]])
    p,dp = ideal_frame_statistics(rho,derivative)
    s = np.trace(derivative[:2,:2]).real
    bloch = np.array([2*derivative[0,1].real,-2*derivative[0,1].imag,
                      derivative[0,0].real-derivative[1,1].real])
    assert np.isclose(np.sum(dp**2),.03**2/2*(3*s*s+bloch@bloch))
    missing = np.array([[0,0,1],[0,0,0],[1,0,0]])
    assert np.linalg.norm(missing)>0
    assert np.allclose(ideal_frame_statistics(rho,missing)[1],0)


def test_no_free_sixfold_shot_gain_and_detector_bounds():
    rate,p,dp = native_statistics(phases("RS_prefix",16),np.array([0,12.00203455]),eta=1.)
    assert np.all((p>=.07)&(p<=.10))
    assert np.allclose(rate,np.sum(dp**2/(p*(1-p)),axis=1)/(6*26.25))
    bad = np.sum(dp**2/(p*(1-p)),axis=1)/26.25
    assert np.allclose(bad,6*rate)


def test_tail_linear_response_against_finite_signal_midpoints():
    delta = 2*np.pi*np.array([0.,12.00203455])
    phase = phases("RS_prefix",16)
    exact,p,dp = native_statistics(phase,delta/(2*np.pi),exponent=0.,amplitude_error=-.02,
                                  qubit_detuning=-.02*4*np.pi)
    eps = 1e-5/16
    values = []
    for b in (eps,-eps):
        u = finite_signal(phase,delta,1.,b,256,amplitude_error=-.02,qubit_detuning=-.02*4*np.pi)
        psi0 = u @ PLUS_X
        probs = []
        for setting in SETTINGS:
            psi = psi0.copy()
            for start,length,phi in analysis_segments(setting,16):
                if not length:
                    continue
                # Independent piecewise time midpoint integration for the tail.
                from experiment import hamiltonian
                h,_ = hamiltonian(delta,0 if phi is None else phi,1.,0 if phi is None else 4*np.pi,-.02,-.02*4*np.pi)
                dt=length/256
                for k in range(256):
                    step=unitary(h+b*np.cos(np.pi*(start+(k+.5)*dt))*Z/2,dt)
                    psi=(step @ psi[...,None])[...,0]
            probs.append(.07+.03*np.abs(psi[:,0])**2)
        values.append(np.array(probs).T)
    numerical=(values[0]-values[1])/(2*eps)
    assert np.max(np.abs(numerical-dp))<2e-6


def test_phase_damping_zero_rate_matches_coherent_readout():
    phase=phases("RS_prefix",16)
    args=dict(amplitude_error=.02,qubit_detuning=-.02*4*np.pi,exponent=0.)
    rate,p,dp=native_statistics(phase,[0,12.02],**args)
    rate2,p2,dp2,diagnostic=dephasing_statistics(phase,[0,12.02],slices=16,**args)
    assert np.allclose(p,p2,atol=1e-11)
    assert np.allclose(dp,dp2,atol=1e-10)
    assert np.allclose(rate,rate2,rtol=1e-9,atol=1e-12)


def test_interpolation_does_not_skip_hidden_vector_zero():
    left=np.array([[1.,0.],[1.,1.]])
    right=np.array([[-1.,0.],[1.,-1.]])
    lower=interpolation_lower(left,right,np.ones(2),0,1e-7)
    assert lower[0]==0
    assert abs(lower[1]-(1-1e-7))<1e-15
    assert curvature_bound()>0


def test_cover_budget_failure_is_not_success():
    x=np.array([12.,16.])
    slopes=np.ones((2,6))
    report,cells,unresolved=continuous_audit(x,slopes,lambda v:np.ones((len(v),6)),maximum_points=2)
    assert not report["conditional_cover_complete"]
    assert len(unresolved)==1
    assert report["conditional_minimum_fi_rate"]==0
