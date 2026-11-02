"""Harbor Pi 0.25 adapter with frozen Qwen3.5-9B metadata and variant skills.

This file is copied unchanged into each variant directory. Harbor imports it as
``piagent_qwen:QwenPi``, the same import path used in the recorded baseline.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import shlex
from pathlib import Path

from harbor.agents.installed.pi import Pi


def _original_pi_base():
    source = os.environ.get("ORIGINAL_PIAGENT_QWEN_FILE")
    if not source:
        return Pi, False
    path = Path(source).resolve(strict=True)
    if path == Path(__file__).resolve():
        raise ValueError("ORIGINAL_PIAGENT_QWEN_FILE points to this variant")
    expected = "fb9eda3d1fe0de6b119708c0845a6ff9f9750f461ec133fefa84aca8dba29170"
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Original Pi adapter hash differs from recorded baseline")
    spec = importlib.util.spec_from_file_location("_original_piagent_qwen", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load original Pi adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.QwenPi
    if not issubclass(original, Pi):
        raise TypeError("Original QwenPi must subclass Harbor Pi")
    return original, True


_BasePi, _USING_ORIGINAL = _original_pi_base()


class QwenPi(_BasePi):
    """Preserve Harbor's Pi lifecycle and add this directory's skills."""

    def _build_custom_models_json(self, access, model_id):
        config = super()._build_custom_models_json(access, model_id)
        if config is None or _USING_ORIGINAL:
            return config
        if model_id == "Qwen3.5-9B":
            model = config["providers"]["harbor-endpoint"]["models"][0]
            model.update(
                {
                    "contextWindow": 262144,
                    "maxTokens": 32768,
                    "samplingParams": {
                        "temperature": 1.0,
                        "top_p": 0.95,
                        "top_k": 20,
                        "presence_penalty": 1.5,
                    },
                    "compat": {"supportsDeveloperRole": False},
                }
            )
        return config

    def _build_register_skills_command(self):
        original = super()._build_register_skills_command()
        commands = [f"({original})"] if original else []
        for skill_file in sorted((Path(__file__).parent / "skills").glob("*/SKILL.md")):
            name = skill_file.parent.name
            if not name.replace("-", "").isalnum():
                raise ValueError(f"Invalid skill name: {name}")
            encoded = base64.b64encode(skill_file.read_bytes()).decode("ascii")
            remote_dir = f'$HOME/.agents/skills/{name}'
            commands.append(
                f'mkdir -p "{remote_dir}" && '
                f'printf %s {shlex.quote(encoded)} | base64 -d > '
                f'"{remote_dir}/SKILL.md"'
            )
        return " && ".join(commands) if commands else None
