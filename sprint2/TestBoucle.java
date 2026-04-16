public class TestBoucle {
    public static void main(String[] args) {
        long n = 10000;
        long x = 0;

        for (long i = 0; i < n; i++) {
            for (long j = 0; j < n; j++) {
                x += 1;
            }
        }
    }
}