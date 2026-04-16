fichier = "../pdfs/Mikolov.txt"

with open(fichier,"r",encoding="utf8") as f:
    lignes = f.readlines()


if lignes[0].find("[") != -1:
    lignes.pop(0)

if lignes[0] == "\n":
    lignes.pop(0)

if lignes[0][-2] == ".":
    titre = lignes.pop(0)
else :
    titre = lignes.pop(0)+lignes.pop(0)
    titre  = titre.replace("\n"," ")

cpt = 0
trouver = False
for ligne in lignes:
    if ligne.lower().find("abstract") != -1:
        trouver = True
        break
    cpt += 1
if not trouver:
    cpt = 0
    for ligne in lignes:
        if ligne == "\n":
            break
        cpt += 1

section_auteurs = lignes[:cpt]
auteurs = ""
for ligne in section_auteurs:
    auteurs += ligne.replace("\n"," ")

cpt2 = 0
for ligne in lignes:
    if ligne.lower().find("introduction") != -1:
        break
    if ligne.lower().find("i ntroduction") != -1:
        break
    cpt2 += 1

section_abstract = lignes[cpt:cpt2]
abstract = ""
for ligne in section_abstract:
    abstract += ligne.replace("\n"," ")

print("Fichier :")
print(fichier+"\n")

print("Titre :")
print(titre+"\n")

print("Auteurs :")
print(auteurs+"\n")

print("Abstract :")
print(abstract)