#include <iostream>
#include <fstream>
#include <string>

int main() {
    std::ifstream fichier("fichier.txt");
    std::string ligne;
    int lignes_compte = 0;

    if (fichier.is_open()) {
        while (getline(fichier, ligne)) {
            lignes_compte++;
        }
        fichier.close();
        std::cout << "Nombre de lignes : " << lignes_compte << "\n";
    } else {
        std::cout << "Impossible d'ouvrir le fichier\n";
    }

    return 0;
}
