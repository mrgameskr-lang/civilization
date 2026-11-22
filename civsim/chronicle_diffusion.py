"""Join local farm acquisitions to observed migration receipts by region and year."""
from dataclasses import replace

from .chronicle_event import Candidate


MOVE_FIELDS = ("source", "target", "people", "distance")


def first_contacts(row):
    sites = row.get("diffusion", {}).get("regions", ())
    if not any(site["new_contact"] for site in sites):
        return
    trials = {r["id"]: (i, r) for i, r in enumerate(row["research"]["regions"])}
    for index, site in enumerate(sites):
        if not site["new_contact"]:
            continue
        contact = site["closing_contact"]
        move_index = contact["move_index"]
        if (site["opening_contact"] is not None or contact["year"] != row["year"]
                or type(move_index) is not int or not 0 <= move_index < len(row["moves"])):
            raise ValueError("first farm contact has no valid migration receipt this year")
        move = row["moves"][move_index]
        if (any(move[key] != contact[key] for key in MOVE_FIELDS) or move["people"] <= 0
                or move["source"] == move["target"] or move["target"] != site["id"]):
            raise ValueError("farm contact differs from the recorded migration")
        source_index, source = trials[move["source"]]
        target_index, target = trials[move["target"]]
        if (source["owner"] != site["owner"] or target["owner"] != site["owner"]
                or source["level_before"] <= 0 or target["level_after"] != 0):
            raise ValueError("farm contact requires a skilled domestic origin and unskilled recipient")
        evidence = {key: f"/moves/{move_index}/{key}" for key in MOVE_FIELDS}
        path = f"/diffusion/regions/{index}"
        evidence.update(move_index=f"{path}/closing_contact/move_index", new_contact=f"{path}/new_contact",
                        source_level=f"/research/regions/{source_index}/level_before",
                        target_level=f"/research/regions/{target_index}/level_after")
        yield Candidate(
            "farm_knowledge_contact", site["owner"], site["id"], 70,
            f"농법을 보유한 지역 {source['id']}에서 이주민 {move['people']:,}명이 도착해 "
            f"지역 {target['id']}에서 이 농법이 처음 전해졌다. 연말 농법 수준은 0이었다.", evidence)


def adoption_origins(row, advances, contacts):
    """Identify the acquisition rule and match a transfer to its first contact, however old."""
    if "diffusion" not in row:
        yield from advances
        return
    sites = {s["id"]: (i, s) for i, s in enumerate(row["diffusion"]["regions"])}
    for event in advances:
        i, site = sites[event.region]
        method = site["closing_method"]
        evidence = dict(event.evidence, method=f"/diffusion/regions/{i}/closing_method")
        if method == "independent":
            yield replace(event, description="두 차례의 유상 시험으로 독자 습득했다. " + event.description,
                          evidence=evidence)
            continue
        contact = contacts.get((event.country, event.region))
        prior = site["opening_contact"]
        if (method != "transfer" or contact is None or prior is None
                or contact["year"] != prior["year"] or not contact["year"] < row["year"]
                or any(contact["evidence"][k]["value"] != prior[k] for k in (*MOVE_FIELDS, "move_index"))):
            raise ValueError("transferred farm acquisition has no matching earlier migration contact")
        evidence["contact_year"] = f"/diffusion/regions/{i}/opening_contact/year"
        yield replace(event, kind="farm_tech_transfer", evidence=evidence,
                      description=f"{prior['year']}년 지역 {prior['source']}에서 전해진 농법을 "
                                  "현지 유상 시험으로 습득했다. " + event.description)
