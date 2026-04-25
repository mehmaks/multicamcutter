"""Pipeline-Orchestrator — führt Module sequenziell aus."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sequencer.context import PipelineContext
from sequencer.module import Module


class PipelineError(Exception):
    """Fehler während der Pipeline-Ausführung mit Modul-Kontext."""

    def __init__(
        self,
        module: str,
        step: int,
        context_keys: List[str],
        original_error: Exception,
    ):
        self.module = module
        self.step = step
        self.context_keys = context_keys
        self.original_error = original_error
        super().__init__(
            f"Modul '{module}' (Schritt {step}) fehlgeschlagen: {original_error}"
        )


class Pipeline:
    """Führt eine geordnete Liste von Modulen gegen einen PipelineContext aus."""

    def __init__(self, modules: List[Module], ctx: PipelineContext):
        self.modules = modules
        self.ctx = ctx

    def validate(self) -> List[str]:
        """Prüft ob jedes Modul seine benötigten Inputs bekommt.

        Returns:
            Liste von Fehlermeldungen (leer = valide).
        """
        available = set(self.ctx.keys())
        errors = []

        for mod in self.modules:
            missing = [k for k in mod.inputs if k not in available]
            if missing:
                errors.append(f"{mod.name}: fehlende Inputs {missing}")
            available.update(mod.outputs)

        return errors

    def run(
        self,
        params: Dict[str, Dict[str, Any]],
        progress_callback: Optional[Callable[[float, str, str], None]] = None,
    ) -> None:
        """Alle Module sequenziell ausführen.

        Args:
            params: {modul_name: {param_name: value}}
            progress_callback: (fraction, module_name, message) -> None
        """
        total = len(self.modules)

        for i, mod in enumerate(self.modules):
            mod_params = params.get(mod.name, {})

            if mod.skip_condition(self.ctx, mod_params):
                if progress_callback:
                    progress_callback(
                        (i + 1) / total, mod.name, f"Übersprungen: {mod.name}"
                    )
                continue

            if progress_callback:
                progress_callback(i / total, mod.name, f"{mod.description or mod.name}")

            # Per-Modul Progress-Callback setzen
            if progress_callback:
                base_frac = i / total
                step_frac = 1.0 / total

                def _module_progress(frac: float, msg: str = "") -> None:
                    progress_callback(
                        base_frac + frac * step_frac, mod.name, msg
                    )

                self.ctx.set_progress_callback(_module_progress)
            else:
                self.ctx.set_progress_callback(None)

            try:
                mod.run(self.ctx, mod_params)
            except PipelineError:
                raise
            except Exception as e:
                raise PipelineError(
                    module=mod.name,
                    step=i,
                    context_keys=sorted(self.ctx.keys()),
                    original_error=e,
                ) from e

        if progress_callback:
            progress_callback(1.0, "done", "Pipeline abgeschlossen")
