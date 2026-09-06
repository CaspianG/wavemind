# H4: posterior certificate for experiment-choice reuse

Let theta index a finite model grid, p its posterior, and L[a,theta] the
probability of binary outcome 1 for experiment a. Cache L for **all** methods.
Using natural logarithms, exact one-step expected information gain is

    I(p,a) = h(sum_theta p_theta L[a,theta])
             - sum_theta p_theta h(L[a,theta]).

Store an anchor posterior q, its maximizing action a*, and its margin g over
the second-best action. Let d = ||p-q||_1/2. For fixed likelihoods,
the predictive probabilities differ by at most d. Binary entropy continuity
gives an upper bound h(d) for d <= 1/2 and log(2) otherwise. The expectation
of h(L) changes by at most d log(2), since h(L) lies in [0,log(2)]. Thus

    B(d) = h(min(d, 1/2)) + d log(2)
    |I(p,a)-I(q,a)| <= B(d).

If g > 2 B(d) + numerical tolerance, a* remains optimal. Otherwise recompute
all scores and replace the anchor. This is a sufficient certificate; it can
be too conservative to save any computation. Ties are recomputed. A cached
decision with an identical posterior may be reused exactly even at a tie.

The bound is an elementary classical entropy argument related to known entropy
continuity results, including the classical binary specialization of
[Audenaert's entropy bound](https://arxiv.org/abs/quant-ph/0610146).
Neither this derivation nor its use of a quantum likelihood
establishes a new physical law or a quantum computational advantage.

For the local falsifier, the quantum dynamics are a single qubit with
H = omega (n dot sigma)/2. Bloch rotation gives the Born probability for
different preparations, readout axes and evolution times. A separately coded
2x2 unitary checks that the likelihood formula represents this physical model.
Finite readout error and a visibility factor represent a declared simple
channel. These are generated probabilities, NOT laboratory measurements.

The certificate concerns choosing a measurement under a fixed model. It does
not certify truth of the model, posterior coverage under misspecification,
Bayes-optimal multi-step policy, or safe transfer across a changed device.
The cache scope must include the likelihood model. The companion H1 test
examines why a matching textual scope cannot establish unchanged physics.
