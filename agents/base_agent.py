class BaseAgent:
    def __init__(self, name: str, uses_llm: bool = False):
        self.name = name           # "Document Processor"
        self.uses_llm = uses_llm   #  False for Agent 1, True for Agent 2
        self.llm_calls_made = 0    # Counter : starts at 0

    def process(self, input_data):
        # Every agent MUST have a process method
        # But each implements it differently
        raise NotImplementedError("Each agent much implement this")
    
    def get_metrics(self):
        # Standard way to report what this agent did
        return {
            'agent_name': self.name,
            'uses_llm': self.uses_llm,
            'llm_calls_made': self.llm_calls_made
        }
        