import litellm
from app.core.logger import get_logger

logger = get_logger(__name__)

def apply_litellm_patch():
    """
    Applies a patch to litellm.completion to handle models that do not
    support the 'stop' parameter, preventing crashes.
    """
    original_completion = litellm.completion

    def patched_completion(*args, **kwargs):
        model_name = None
        if 'model' in kwargs:
            model_name = kwargs['model']
        elif args:
            model_name = args[0]

        model_name_str = str(model_name).lower() if model_name else ""

        if ('grok' in model_name_str or 'o4' in model_name_str) and 'stop' in kwargs:
            logger.info(f"LITELLM PATCH: Removing 'stop' parameter for model '{model_name}'.")
            kwargs.pop('stop')

        if 'model' in kwargs:
            kwargs['model'] = kwargs['model'].replace("models/", "").replace("model=", "")
        elif args:
            new_args = list(args)
            new_args[0] = new_args[0].replace("models/", "")
            args = tuple(new_args)

        return original_completion(*args, **kwargs)

    litellm.completion = patched_completion
    logger.info("LiteLLM patch applied successfully.")

