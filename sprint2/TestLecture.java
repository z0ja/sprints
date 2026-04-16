import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;

public class TestLecture {
    public static void main(String[] args) {
        int lignesCompte = 0;
        
        try (BufferedReader br = new BufferedReader(new FileReader("fichier.txt"))) {
            String ligne;
            while ((ligne = br.readLine()) != null) {
                lignesCompte++;
            }
            System.out.println("Nombre de lignes : " + lignesCompte);
        } catch (IOException e) {
            System.out.println("Erreur de lecture : " + e.getMessage());
        }
    }
}