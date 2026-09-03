import os
from typing import Dict, Optional

from dotenv import load_dotenv


def resolve_openai_api_key() -> Optional[str]:
    """Resolve the OpenAI key from Streamlit Secrets first, then environment variables.

    This keeps local development and Streamlit Cloud aligned without forcing the caller
    to know where the secret is stored.
    """
    try:
        import streamlit as st  # Local import so non-Streamlit code can still use this helper.

        if hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets:
            key = str(st.secrets["OPENAI_API_KEY"]).strip()
            if key:
                return key
    except Exception:
        pass

    # Streamlit does not execute the CLI entrypoint, so load a local .env here.
    # Existing environment variables always win because override=False.
    load_dotenv(override=False)
    key = os.getenv("OPENAI_API_KEY")
    return key.strip() if key else None


class LLMInterface:
    """
    Centralized OpenAI Responses API adapter.

    The model can only return a caller-supplied JSON schema. Financial amounts,
    dates and debit/credit direction never come back through this interface.
    """

    def __init__(self, api_key: str, model: str = "gpt-5.6"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.call_count = 0
        self.total_cost = 0.0
        self.input_tokens = 0
        self.output_tokens = 0

    def make_call(
        self,
        prompt: str,
        system_prompt: str = None,
        expect_json: bool = False,
        response_schema: Optional[Dict] = None,
    ) -> Optional[str]:
        """
        Single point for ALL LLM calls in your system
        Every agent must use this method
        """
        self.call_count += 1
        print(f"🤖 LLM Call #{self.call_count} - OpenAI API")

        try:
            # Structured Outputs are mandatory for the categorization agent.
            request_payload = {
                "model": self.model,
                "instructions": system_prompt or "Follow the user's instructions.",
                "input": prompt,
                "max_output_tokens": 10000,
                "store": False,
            }
            if expect_json:
                if response_schema:
                    request_payload["text"] = {
                        "format": {
                            "type": "json_schema",
                            "name": "financial_analyzer_response",
                            "strict": True,
                            "schema": response_schema,
                        }
                    }
                else:
                    request_payload["text"] = {
                        "format": {"type": "json_object"}
                    }

            response = self.client.responses.create(**request_payload)

            usage = getattr(response, "usage", None)
            self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

            if getattr(response, "status", "completed") != "completed":
                raise RuntimeError(
                    f"OpenAI response did not complete (status={response.status})"
                )

            content = getattr(response, "output_text", None)
            if not content:
                return None
            return content
        
        except Exception as e:
            error_msg = f"❌ OpenAI API call failed: {e}"
            print(error_msg)
            raise RuntimeError(error_msg)
        
    def get_metrics(self) -> Dict:
        """Report usage statistics"""
        return {
            'total_calls': self.call_count,
            'estimated_cost': self.total_cost,
            'average_cost_per_call': 0.0,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'model': self.model,
            'cost_tracked': False,
        }
        
    def reset_counters(self):
        """Reset for new analysis session"""
        self.call_count = 0
        self.total_cost = 0.0
        self.input_tokens = 0
        self.output_tokens = 0


class DeterministicLLMInterface:
    """Metrics-compatible replacement used when remote model calls are disabled."""

    def __init__(self):
        self.call_count = 0
        self.total_cost = 0.0

    def make_call(self, *args, **kwargs):
        raise RuntimeError("LLM calls are disabled in deterministic mode")

    def get_metrics(self) -> Dict:
        return {
            'total_calls': 0,
            'estimated_cost': 0.0,
            'average_cost_per_call': 0.0,
            'input_tokens': 0,
            'output_tokens': 0,
            'model': None,
            'cost_tracked': False,
        }

    def reset_counters(self):
        self.call_count = 0
        self.total_cost = 0.0
