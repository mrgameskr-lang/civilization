"""Observe completed local farm trials and the first production ledger using them."""
from .chronicle_event import Candidate


def farm_adoptions(row):
    for index, research in enumerate(row.get("research", {}).get("regions", ())):
        before, after = research["level_before"], research["level_after"]
        if after <= before:
            continue
        if research["adoption_year"] != row["year"]:
            raise ValueError("farm technique completion year differs from the recorded level change")
        base = f"/research/regions/{index}"
        evidence = {k: f"{base}/{k}" for k in
                    ("id", "owner", "adoption_year", "level_before", "level_after", "project_id",
                     "trial_workers", "trial_ore", "trial_tools",
                     "cumulative_workers", "cumulative_ore", "cumulative_tools")}
        project_id = research["project_id"]
        project = row["government"]["works"]["projects"][project_id]
        if (project["project_id"] != project_id or project.get("field_trial") is not True
                or project["target"] != research["id"] or project["owner"] != research["owner"]):
            raise ValueError("completed farm technique has no matching paid public project")
        source = f"/government/works/projects/{project_id}"
        evidence.update(project_trial=f"{source}/field_trial", project_target=f"{source}/target",
                        project_workers_total=f"{source}/workers", project_ore_total=f"{source}/used/ore",
                        project_tools_total=f"{source}/used/tools")
        yield Candidate(
            "farm_tech_adoption", research["owner"], research["id"], 90,
            f"이 지역이 연말에 새 농법을 습득해 농법 수준이 {before}에서 {after}로 올랐다. "
            f"시험에 누적 노동 {research['cumulative_workers']:,}인년, "
            f"광석 {research['cumulative_ore']:,}단위, 도구 {research['cumulative_tools']:,}단위를 썼다.",
            evidence,
        )


def farm_applications(row):
    """Associate each first-use production with its originating country, region and year."""
    first = [(i, r) for i, r in enumerate(row.get("research", {}).get("regions", ()))
             if r["first_application"]]
    if not first:
        return
    by_region = {r["id"]: (i, r) for i, r in enumerate(row["regions"])}
    for research_index, research in first:
        prod_index, region = by_region[research["id"]]
        if (region["owner"] != research["owner"] or research["adoption_year"] + 1 != row["year"]
                or region["production"]["farm_tech_level"] != research["level_before"]
                or research["level_before"] <= 0):
            raise ValueError("first farm application differs from the region's effective technique")
        source = f"/regions/{prod_index}"
        trial = f"/research/regions/{research_index}"
        key = (research["owner"], research["id"], research["adoption_year"])
        yield key, {"region": f"{source}/id", "owner": f"{source}/owner",
                    "adoption_year": f"{trial}/adoption_year", "first_application": f"{trial}/first_application",
                    "farm_tech_level": f"{source}/production/farm_tech_level",
                    "food_produced": f"{source}/production/produced/food",
                    "food_without_tech": f"{source}/production/food_without_tech"}
