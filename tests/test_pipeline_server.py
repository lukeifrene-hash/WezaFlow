import unittest

from services.pipeline.models import AppContext, PipelineResult

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None


class PipelineServerTests(unittest.TestCase):
    def test_serialize_result_handles_no_speech(self):
        from services.pipeline_server import serialize_result

        self.assertEqual({"status": "no_speech"}, serialize_result(None))

    def test_serialize_result_returns_pipeline_payload(self):
        from services.pipeline_server import serialize_result

        result = PipelineResult(
            raw_transcript="hello",
            polished_text="Hello.",
            app_context=AppContext(
                app_name="Code.exe",
                window_title="LocalFlow",
                category="code",
                browser_url=None,
                visible_text=[],
            ),
            duration_ms=42,
        )

        payload = serialize_result(result)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["raw_transcript"], "hello")
        self.assertEqual(payload["polished_text"], "Hello.")
        self.assertEqual(payload["app_context"]["category"], "code")

    def test_create_app_exposes_runtime_status_routes(self):
        if TestClient is None:
            self.skipTest("fastapi is not installed in this Python environment")
        from services.pipeline_server import create_app

        client = TestClient(create_app(pipeline=object()))

        payload = client.get("/status").json()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["profile"], "low-impact")


if __name__ == "__main__":
    unittest.main()
