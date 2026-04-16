import os, sys, time


if len(sys.argv) < 2:
    print("chemins du dossier de pdf manquant")
    sys.exit(1)


dossier = sys.argv[1]

fichiers = os.listdir(dossier)

destination = os.path.join(dossier,"txt")
if not os.path.exists(destination):
    os.mkdir(destination)


for fichier in fichiers:
    try :
        fichier_pdf = os.path.join(dossier,fichier)

        os.system(f"pdftotext {fichier_pdf}")

        fichier_txt = fichier_pdf.replace(".pdf",".txt")

        with open(fichier_txt,"r",encoding="utf8") as f:
            lignes = f.readlines()
        os.remove(fichier_txt)

        while lignes[1] == "\n":
            lignes.pop(0)
            lignes.pop(0)

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

        with open(os.path.join(destination, fichier.replace(".pdf",".txt")), "w") as f:
            f.write("Fichier :\n")
            f.write(fichier+"\n")

            f.write("Titre :\n")
            f.write(titre+"\n")

            f.write("Auteurs :\n")
            f.write(auteurs+"\n")

            f.write("Abstract :\n")
            f.write(abstract+"\n")
    except:
        pass