"""Verify all workflow indexes route to local components without loading weight tensors."""

from pathlib import Path

from h3_config import WORKFLOWS


def verify_workflow_indexes(snapshot: Path) -> dict[str, list[str]]:
    from diffusers import ModularPipeline

    routes = {}
    for workflow in WORKFLOWS:
        pipe = ModularPipeline.from_pretrained(str(snapshot), workflow=workflow, local_files_only=True)
        sources = {name: spec for name, spec in pipe._component_specs.items()
                   if spec.pretrained_model_name_or_path is not None}
        folders = []
        for name, spec in sources.items():
            if Path(spec.pretrained_model_name_or_path).resolve() != snapshot.resolve():
                raise RuntimeError(f"{workflow}/{name} did not resolve to the pinned local snapshot")
            folders.append(spec.subfolder)
        expected = "transformer_ref" if workflow == "ref2va" else "transformer"
        other = "transformer" if workflow == "ref2va" else "transformer_ref"
        if expected not in folders or other in folders:
            raise RuntimeError(f"Unexpected transformer routing for {workflow}: {folders}")
        routes[workflow] = sorted(folders)
        print(f"Local workflow index OK: {workflow}, {expected}")
    return routes


if __name__ == "__main__":
    from download_model import local_snapshot

    verify_workflow_indexes(local_snapshot())
