"""The few jq calls referee.sh makes, for machines without jq. CI runners have the real one and don't use this."""
import json
import sys


def main(args: list[str]) -> int:
    if args[0] == "-e":  # jq -e 'type == "object"'
        try:
            return 0 if isinstance(json.loads(sys.stdin.read()), dict) else 1
        except ValueError:
            return 1
    if args[0] == "-c":  # jq -c . <file>
        with open(args[2], encoding="utf-8") as handle:
            print(json.dumps(json.load(handle)))
        return 0
    # jq -n --arg name value ... --argjson name value ... <filter>: enough of the result for the tests to read
    values, index = {}, 1
    while index < len(args) - 1:
        flag, name, value = args[index:index + 3]
        values[name] = json.loads(value) if flag == "--argjson" else value
        index += 3
    print(json.dumps({**values["sql"], "journey_passed": values["jpass"], "verdict": values["verdict"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
