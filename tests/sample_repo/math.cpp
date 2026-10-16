#include <iostream>

class MathHelper {
public:
    int multiply(int a, int b) {
        return a * b;
    }
};

int main() {
    MathHelper m;
    return m.multiply(4, 5);
}
