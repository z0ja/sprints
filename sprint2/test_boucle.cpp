#include <iostream>

int main() {
    long long n = 10000;
    long long x = 0;

    for (long long i = 0; i < n; ++i) {
        for (long long j = 0; j < n; ++j) {
            x += 1;
        }
    }
    return 0;
}
