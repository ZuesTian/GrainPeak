import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webapp import app, parse_two_column_text  # noqa: E402


SAMPLE_TEXT = "x,y\n0.1,0.2\n0.2,0.5\n0.3,1.0\n0.4,0.5\n0.5,0.2\n"


class GrainPeakWebTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["service"], "grainpeak")

    def test_parser_skips_header_and_sorts(self):
        x, y = parse_two_column_text("name,value\n3,30\n1,10\n2,20\n4,40")
        self.assertEqual(x.tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(y.tolist(), [10.0, 20.0, 30.0, 40.0])

    def test_fit_returns_metrics_and_peaks(self):
        response = self.client.post("/api/fit", json={"text": SAMPLE_TEXT, "model": "gaussian", "peak_count": 1, "axis_mode": "linear"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["point_count"], 5)
        self.assertEqual(len(body["peaks"]), 1)
        self.assertIn("r_squared", body)

    def test_invalid_data_is_rejected(self):
        response = self.client.post("/api/fit", json={"text": "x,y\n1,2"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
