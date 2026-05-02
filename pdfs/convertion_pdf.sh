# Compter les fichiers PDF
pdf_files=(*.pdf)
if [ ${#pdf_files[@]} -eq 0 ] || [ ! -f "${pdf_files[0]}" ]; then
    echo "Aucun fichier PDF trouvé dans le dossier courant."
    exit 0
fi

# Convertir chaque fichier PDF
echo "Conversion des fichiers PDF en cours..."
for pdf in *.pdf; do
    # Vérifier si c'est bien un fichier (évite le cas où aucun PDF n'existe)
    [ -f "$pdf" ] || continue
    
    # Générer le nom du fichier de sortie (remplace .pdf par .txt)
    txt_file="${pdf%.pdf}.txt"
    
    echo "Traitement de: $pdf -> $txt_file"
    
    # Exécuter pdftotext avec l'option -layout
    if pdftotext "$pdf" "$txt_file"; then
        echo "  ✓ Conversion réussie"
    else
        echo "  ✗ Erreur lors de la conversion de $pdf"
    fi
done

echo "Conversion terminée."