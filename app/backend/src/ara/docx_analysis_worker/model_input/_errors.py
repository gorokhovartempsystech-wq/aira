"""Fixed diagnostics never include a document, tokenizer or model path/content."""


class ModelInputError(ValueError):
    MESSAGES = {
        "invalid_input": "Invalid model input.",
        "model_unavailable": "Model package or tokenizer is unavailable.",
        "model_input_limit_exceeded": "Input exceeds the model token limit.",
        "adapter_error": "Model adapter did not complete.",
    }

    def __init__(self, code):
        self.code = code
        super().__init__(self.MESSAGES[code])


def require(condition, code="model_unavailable"):
    if not condition:
        raise ModelInputError(code)
