import json
import subprocess

import pipeline_submit


class DummyLogger:
    def __init__(self):
        self.messages = {"info": [], "error": [], "debug": []}

    def info(self, msg, *args):
        self.messages["info"].append(msg % args if args else msg)

    def error(self, msg, *args):
        self.messages["error"].append(msg % args if args else msg)

    def debug(self, msg, *args):
        self.messages["debug"].append(msg % args if args else msg)


def test_build_payload_format():
    payload = pipeline_submit._build_payload(67, -0.07178)
    assert payload == "topic_id: 67 value: -0.07178"


def test_submit_passes_single_payload_argument(monkeypatch):
    dummy_logger = DummyLogger()
    sent_commands = []

    monkeypatch.setenv("ALLORA_CHAIN_ID", "chain-x")
    monkeypatch.setenv("ALLORA_NODE", "http://localhost:26657")
    monkeypatch.setenv("ALLORA_FEES", "1utoken")
    monkeypatch.setenv("ALLORA_GAS", "123456")

    monkeypatch.setattr(pipeline_submit.shutil, "which", lambda name: "/usr/bin/allorad")

    def fake_run(cmd, capture_output, text, timeout):
        sent_commands.append(cmd)
        response = {"code": 0, "txhash": "ABC123"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(pipeline_submit.subprocess, "run", fake_run)

    success, tx_hash = pipeline_submit.submit_prediction_to_chain(
        topic_id=67, value=-0.07178, wallet="allo1abc", logger=dummy_logger
    )

    assert success is True
    assert tx_hash == "ABC123"

    assert sent_commands, "Submission command was not invoked"
    command = sent_commands[0]

    # The payload should be a single argument containing both fields in proto-text form
    assert command[5] == "topic_id: 67 value: -0.07178"
    assert command[0:6] == [
        "/usr/bin/allorad",
        "tx",
        "emissions",
        "insert-worker-payload",
        "allo1abc",
        "topic_id: 67 value: -0.07178",
    ]
