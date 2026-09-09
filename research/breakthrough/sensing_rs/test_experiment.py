"""Implementation checks, not evidence of scientific novelty or device gain."""

import numpy as np
import pytest

from experiment import (Z, analytic_leakage, finite_signal, fisher, hamiltonian,
                        integral_exp, phases, propagate, pulse_response, rs, unitary)


def test_sequences_and_prefix():
    assert rs(8).tolist() == [1, 1, 1, -1, 1, 1, -1, 1]
    s = np.rint(np.cos(phases("RS_prefix", 64))).astype(int)
    assert np.array_equal(np.r_[1, np.cumprod(s)], rs(65))
    assert not np.array_equal(phases("RS_prefix", 64), phases("raw_RS", 64))
    assert np.allclose(phases("MLEV8", 8)/(np.pi/2), [0, 0, 2, 2, 2, 0, 0, 2])
    assert np.allclose(phases("XY16", 16)/(np.pi/2), [0,1,0,1,1,0,1,0,2,3,2,3,3,2,3,2])


def test_input_rejections():
    for n in (0, 2, 3, 12):
        with pytest.raises(ValueError):
            phases("RS_prefix", n)
    with pytest.raises(ValueError):
        phases("XY16", 8)


def test_integral_degeneracy_and_symmetry():
    x = np.array([0, 1e-15, -2.7, 2.7])
    j = integral_exp(x, 0.3)
    assert abs(j[0]-0.3) < 1e-15
    assert abs(j[1]-0.3) < 1e-14
    assert abs(j[2]-j[3].conjugate()) < 1e-15


def test_complementary_norm_identity():
    w = np.exp(2j*np.pi*np.linspace(0, 1, 131))
    for n in (1, 2, 4, 8, 16, 32, 64):
        p = np.polynomial.polynomial.polyval(w, rs(n))
        q = np.polynomial.polynomial.polyval(-w, rs(n))
        assert np.max(np.abs(np.abs(p)**2+np.abs(q)**2-2*n)) < 2e-10


def test_pulse_derivative_vs_finite_difference_with_degeneracy():
    delta = np.array([0, 2*np.pi, 2*np.pi*2.375])
    h, dh = hamiltonian(delta, np.pi/2, 0, 4*np.pi)
    u, du = pulse_response(h, dh, 0.25)
    step = 2e-6
    numerical = (unitary(h+step*dh, 0.25)-unitary(h-step*dh, 0.25))/(2*step)
    assert np.max(np.abs(numerical-du)) < 2e-8
    assert np.max(np.abs(u.conj().swapaxes(-1,-2)@u-np.eye(3))) < 1e-13


def test_signal_response_vs_separate_finite_time_integrator():
    phase = phases("RS_prefix", 16)
    delta = np.array([0.0, 2*np.pi*2.375, 2*np.pi*12.0625])
    u, du = propagate(phase, delta, eta=1.0, amplitude_error=0.02,
                      qubit_detuning=-0.02*4*np.pi, derivative="signal")
    step = 1e-5/16
    estimates = []
    for slices in (128, 256):
        plus = finite_signal(phase, delta, 1.0, step, slices,
                             amplitude_error=0.02, qubit_detuning=-0.02*4*np.pi)
        minus = finite_signal(phase, delta, 1.0, -step, slices,
                              amplitude_error=0.02, qubit_detuning=-0.02*4*np.pi)
        estimates.append((plus-minus)/(2*step))
    scaled = np.max(np.abs(estimates[-1]-du))/(1+np.max(np.abs(du)))
    assert scaled < 3e-6
    assert np.max(np.abs(estimates[-1]-du)) < np.max(np.abs(estimates[0]-du))
    assert np.max(np.abs(u.conj().swapaxes(-1,-2)@u-np.eye(3))) < 2e-12


def test_closed_row_including_boundary_and_negative_control():
    n = 64
    delta = 2*np.pi*np.array([0.0, 0.25, 0.2503, 1.13, -2.371, 6.0])
    _, exact = propagate(phases("RS_prefix", n), delta)
    row, bound = analytic_leakage(n, delta)
    assert np.max(np.abs(exact[:, 2, :2]-row)) < 1e-10
    assert np.all(np.sum(np.abs(row)**2, axis=1) <= bound+1e-10)
    # CP is not allowed to inherit the candidate's bound.
    _, bad = propagate(phases("CP", n), delta)
    assert np.any(np.sum(np.abs(bad[:, 2, :2])**2, axis=1) > bound+1e-3)


def test_ideal_signal_and_complete_shot_accounting():
    rates = []
    for name in ("RS_prefix", "CP", "APCP", "XY16", "MLEV8"):
        u, du = propagate(phases(name, 64), np.array([0.0]), derivative="signal")
        fi, p, _ = fisher(u, du)
        assert abs(p[0]-0.5) < 1e-11
        rates.append(fi[0])
    assert np.ptp(rates) < 2e-8
    # A deliberate unitary that completely removes |+x> from the sensor
    # subspace must not be rescued by conditioning on surviving shots.
    with pytest.raises(ArithmeticError):
        fisher(np.zeros((1,3,3), complex), np.zeros((1,3,3), complex))


def test_zero_coupling_no_leakage_and_eta_parity():
    phase = phases("RS_prefix", 16)
    delta = 2*np.pi*np.array([-1.13, 0, 12.5])
    u0, _ = propagate(phase, delta)
    up, _ = propagate(phase, delta, eta=0.1)
    um, _ = propagate(phase, delta, eta=-0.1)
    assert np.max(np.abs(u0[:,2,:2])) < 1e-13
    assert np.max(np.abs(up[:,2,:2]+um[:,2,:2])) < 1e-12
    assert np.max(np.abs(up[:,:2,:2]-um[:,:2,:2])) < 1e-12
