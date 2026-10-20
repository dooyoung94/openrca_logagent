import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from logagent_bench.hf_loop import CONFIG
from logagent_bench.hf_transport import LocalToolClient, serialize_request, tool_envelope_schema

SDK = importlib.util.find_spec("agent_rca_bench") is not None
HF = importlib.util.find_spec("llama_cpp") is not None


class SerializationTests(unittest.TestCase):
    def test_original_prompt_and_tool_schemas_are_not_rewritten(self):
        tools=[{"name":"query","input_schema":{"type":"object","properties":{"q":{"type":"string"}}}}]
        original=copy.deepcopy(tools)
        prompt=serialize_request("ORIGINAL SYSTEM",tools,[{"role":"user","content":"ORIGINAL INCIDENT"},
            {"role":"assistant","content":[{"type":"tool_use","name":"query","input":{"q":"SELECT observed FROM telemetry"}}]},
            {"role":"user","content":[{"type":"tool_result","content":"ACTUAL RESULT"}]}])
        self.assertEqual(tools,original)
        self.assertTrue(prompt.startswith("<|im_start|>system\nORIGINAL SYSTEM<|im_end|>"))
        self.assertIn("ORIGINAL INCIDENT",prompt)
        self.assertIn("ACTUAL RESULT",prompt)
        self.assertEqual(tool_envelope_schema(tools)["anyOf"][0]["properties"]["arguments"],tools[0]["input_schema"])


@unittest.skipUnless(SDK and HF,"Install .[hf,llm] for local transport contract tests")
class LocalTransportTests(unittest.TestCase):
    @staticmethod
    def model(finish_reason="stop"):
        class FakeModel:
            def __init__(self):
                self.resets=0
                self.requests=[]
            def reset(self):self.resets+=1
            def tokenize(self,prompt,add_bos):return [1]*12
            def create_completion(self,**kwargs):
                self.requests.append(kwargs)
                return {"choices":[{"text":json.dumps({"tool_name":"ping","arguments":{"message":"ok"}}),
                                    "finish_reason":finish_reason}],
                        "usage":{"prompt_tokens":12,"completion_tokens":10}}
        return FakeModel()

    def test_generated_arguments_pass_through_without_answer_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            model=self.model()
            client=LocalToolClient(model,CONFIG,Path(temporary)/"private",17)
            tools=[{"name":"ping","input_schema":{"type":"object","properties":{"message":{"type":"string"}},
                                                        "required":["message"],"additionalProperties":False}}]
            response=client.create(model="HF",max_tokens=16384,system="original",tools=tools,
                                   messages=[{"role":"user","content":"use a tool"}])
            self.assertEqual(response.content[0].input,{"message":"ok"})
            self.assertEqual(model.resets,1)
            self.assertEqual(model.requests[0]["seed"],17)
            self.assertEqual(model.requests[0]["max_tokens"],16384)
            self.assertEqual(client.trace[0]["completion_tokens"],10)

    def test_context_capacity_fails_before_inference_without_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            model=self.model()
            client=LocalToolClient(model,CONFIG,Path(temporary)/"private",17)
            with self.assertRaisesRegex(RuntimeError,"context capacity"):
                client.create(model="HF",max_tokens=32768,system="original",tools=[],messages=[])
            self.assertEqual(client.calls,0)
            self.assertEqual(model.requests,[])

    def test_output_exhaustion_is_recorded_and_not_converted_to_a_valid_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            model=self.model("length")
            client=LocalToolClient(model,CONFIG,Path(temporary)/"private",17)
            tools=[{"name":"ping","input_schema":{"type":"object","properties":{"message":{"type":"string"}}}}]
            with self.assertRaisesRegex(RuntimeError,"not repaired"):
                client.create(model="HF",max_tokens=16384,system="original",tools=tools,messages=[])
            self.assertEqual(client.calls,1)
            self.assertEqual(client.trace[0]["finish_reason"],"length")


if __name__=="__main__":
    unittest.main()
