from collections import OrderedDict


def normalize(text: str) -> str:
    return (
        text.lower()
        .replace(".", "")
        .replace(",", "")
        .replace("$", "")
        .strip()
    )


def deduplicate_answers(answers):
    merged = OrderedDict()

    for answer in answers:
        key = normalize(answer["fact"])

        if key not in merged:
            merged[key] = answer
            continue

        existing = merged[key]

        existing_sources = {
            (s["filename"], s["chunk"])
            for s in existing["sources"]
        }

        for source in answer["sources"]:
            pair = (source["filename"], source["chunk"])

            if pair not in existing_sources:
                existing["sources"].append(source)

    return list(merged.values())