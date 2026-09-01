from core.assembly_snapshot import load_from_selection


class AssembliesController:
    def __init__(self, fusion=None):
        self.fusion = fusion

    def load_from_selection(self, _payload, _palette):
        if self.fusion is None:
            return (
                "assemblyLoadResult",
                {
                    "ok": False,
                    "action": "assemblies.loadFromSelection",
                    "code": "no_fusion",
                    "errors": ["Fusion adapter is unavailable; reload the plugin in an active design."],
                },
            )
        getter = getattr(self.fusion, "get_selected_entities", None)
        entities = getter() if callable(getter) else []
        result = load_from_selection(entities)
        return ("assemblyLoadResult", result)
