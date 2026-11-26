import json
import unittest

from simulation import (
    lambda_handler,
    run_monte_carlo,
    run_simulation,
    wilson_confidence_interval,
)


class SimulationTests(unittest.TestCase):
    def test_seed_reproduces_the_complete_result(self):
        payload = {
            "seed": 1234,
            "duration_s": 2.0,
            "threat_count": 5,
            "dt_s": 0.05,
        }
        self.assertEqual(run_simulation(payload), run_simulation(payload))

    def test_lambda_handler_accepts_json_body(self):
        result = lambda_handler({"body": '{"mode":"det","seed":9,"duration_s":1}'})
        self.assertEqual(result["mode"], "det")
        self.assertEqual(result["seed"], 9)
        self.assertEqual(result["counts"]["spawned"], 1)
        json.dumps(result)

    def test_rejects_out_of_range_integration_step(self):
        with self.assertRaisesRegex(ValueError, "dt_s"):
            run_simulation({"dt_s": 0.1})

    def test_result_exposes_fsm_states_and_performance_indicators(self):
        result = run_simulation(
            {"mode": "det", "seed": 5, "duration_s": 1.0, "dt_s": 0.05}
        )
        self.assertEqual(set(result["counts"]["states"]), {f"S{i}" for i in range(7)})
        self.assertGreaterEqual(result["throughput_per_s"], 0.0)
        self.assertGreaterEqual(result["average_wait_time_s"], 0.0)

    def test_saturated_salvo_uses_queue_and_measures_wait(self):
        result = run_simulation(
            {
                "mode": "det",
                "seed": 1,
                "threat_count": 20,
                "salvo_interval_s": 0.5,
                "fire_control_latency_s": 3,
                "duration_s": 90,
                "dt_s": 0.05,
            }
        )
        self.assertGreater(result["counts"]["max_fire_queue"], 0)
        self.assertGreater(result["average_wait_time_s"], 0.0)
        self.assertGreaterEqual(result["counts"]["interceptors_remaining"], 0)
        self.assertGreater(result["counts"]["neutralized"], 0)
        self.assertGreater(result["counts"]["impacts"], 0)
        self.assertGreater(result["counts"]["harmless"], 0)
        self.assertEqual(result["counts"]["processed"], result["counts"]["spawned"])

    def test_wilson_interval_is_bounded_and_includes_the_estimate(self):
        lower, upper = wilson_confidence_interval(50, 100)
        self.assertAlmostEqual(lower, 0.4038, places=4)
        self.assertAlmostEqual(upper, 0.5962, places=4)
        self.assertLessEqual(lower, 0.5)
        self.assertGreaterEqual(upper, 0.5)

    def test_monte_carlo_runs_at_least_100_replications_for_each_salvo(self):
        result = run_monte_carlo(
            {
                "runs": 100,
                "mode": "est",
                "seed": 17,
                "duration_s": 9.5,
                "dt_s": 0.05,
                "salvo_interval_s": 0.5,
            }
        )
        self.assertEqual(result["total_runs"], 300)
        self.assertEqual(
            [group["threat_count"] for group in result["groups"]],
            [5, 10, 20],
        )
        for group in result["groups"]:
            self.assertEqual(group["runs"], 100)
            self.assertGreaterEqual(group["confidence_interval_95"]["lower"], 0)
            self.assertLessEqual(group["confidence_interval_95"]["upper"], 1)

    def test_monte_carlo_rejects_small_samples_and_deterministic_mode(self):
        with self.assertRaisesRegex(ValueError, "runs"):
            run_monte_carlo({"runs": 99})
        with self.assertRaisesRegex(ValueError, "estocástico"):
            run_monte_carlo({"runs": 100, "mode": "det"})
        with self.assertRaisesRegex(ValueError, "20 amenazas"):
            run_monte_carlo(
                {"runs": 100, "mode": "est", "duration_s": 1.0}
            )

    def test_lambda_handler_routes_monte_carlo_operation(self):
        result = lambda_handler(
            {
                "body": json.dumps(
                    {
                        "operation": "monte_carlo",
                        "runs": 100,
                        "mode": "est",
                        "duration_s": 9.5,
                        "dt_s": 0.05,
                        "salvo_interval_s": 0.5,
                    }
                )
            }
        )
        self.assertEqual(result["total_runs"], 300)
        self.assertEqual(result["interval_method"], "Wilson")

    def test_seeded_kill_probability_allows_reproducible_failures_in_det_mode(self):
        payload = {
            "mode": "det",
            "seed": 1,
            "threat_count": 20,
            "salvo_interval_s": 0.5,
            "fire_control_latency_s": 3,
            "interceptor_count": 8,
            "kill_probability": 0.6,
            "duration_s": 90,
            "dt_s": 0.05,
        }
        first = run_simulation(payload)
        second = run_simulation(payload)
        self.assertGreater(first["counts"]["failed_detonations"], 0)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
