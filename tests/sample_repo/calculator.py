class BaseCalculator:
    def reset(self):
        pass

class Calculator(BaseCalculator):
    def __init__(self, initial: int = 0):
        self.val = initial

    def add(self, x: int) -> int:
        return self.val + x

def run_calc():
    c = Calculator(5)
    return c.add(10)
