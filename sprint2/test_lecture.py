lignes_compte = 0

with open("fichier.txt", "r", encoding="utf-8") as fichier:
    for ligne in fichier:
        lignes_compte += 1

print(f"Nombre de lignes : {lignes_compte}")