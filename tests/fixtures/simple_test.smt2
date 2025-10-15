; Simple SMT2 test - check if 2 > 1
(declare-const x Int)
(declare-const y Int)

(assert (= x 2))
(assert (= y 1))
(assert (> x y))

(check-sat)
(get-model)
