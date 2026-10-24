"""Audited model snapshot; review its component layout before changing revisions."""

MODEL_ID = "MiniMaxAI/MiniMax-H3"
MODEL_REVISION = "42ed227ee7df40d41602854ae760620d6eb651fe"
COMPONENTS = (
    "transformer", "transformer_ref", "text_encoder", "tokenizer", "processor", "vae",
    "audio_vae", "scheduler", "audio_scheduler",
)
ROOT_CONFIGS = ("model_index.json", "modular_model_index.json")
WORKFLOWS = ("t2va", "fl2va", "ref2va")
WEIGHT_COMPONENTS = ("transformer", "transformer_ref", "text_encoder", "vae", "audio_vae")
MANIFEST_SCHEMA = 2
MODEL_PROFILE = "h3-full-diffusers"
GIB = 1024**3
