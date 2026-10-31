"""Read Challenge status for owned Runs without exposing any answer."""
import argparse
import json

from commerce_api.integrations.legacy.verification import relay
from commerce_api.runtime.runs import Run
from commerce_api.runtime.storage import Paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_ids", nargs="+")
    args = parser.parse_args()
    service = relay()
    base_url, token = service.relay_settings()
    results = []
    for run_id in args.run_ids:
        run = Run.load(Paths(), run_id)
        for name, operation in run.state["operations"].items():
            identifier = operation.get("challenge_id")
            if not identifier:
                continue
            state = service.json_request(f"{base_url}/api/automation/verification/challenges/{identifier}", token=token)
            safe = {key: state[key] for key in ("status", "created_at", "expires_at", "answered_at", "answer_source") if key in state}
            # Only the presence is exposed, never the answer, phone, message or
            # service response. No Challenge mutation or notice is performed.
            results.append({"run_id": run_id, "operation": name, **safe, "answer_present": bool(state.get("answer"))})
    print(json.dumps({"challenges": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
