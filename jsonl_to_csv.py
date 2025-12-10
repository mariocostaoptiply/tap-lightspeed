#!/usr/bin/env python3
"""
Script para converter ficheiros JSONL (do target-jsonl) para CSV.
Uso: python jsonl_to_csv.py [diretório_output]
"""

import json
import csv
import sys
import shutil
from pathlib import Path
from typing import Dict, Any, List


def jsonl_to_csv(jsonl_path: Path, csv_path: Path) -> None:
    """Converte um ficheiro JSONL para CSV."""
    records: List[Dict[str, Any]] = []
    
    # Ler todas as linhas do JSONL
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Suportar dois formatos:
                # 1. Formato Singer: {"type": "RECORD", "record": {...}}
                # 2. Formato direto: {"id": "...", "name": "...", ...}
                if record.get('type') == 'RECORD':
                    # Formato Singer
                    records.append(record.get('record', {}))
                elif 'type' not in record or record.get('type') not in ['SCHEMA', 'STATE']:
                    # Formato direto (assumir que é um record se não for SCHEMA ou STATE)
                    records.append(record)
            except json.JSONDecodeError as e:
                print(f"Erro ao processar linha em {jsonl_path}: {e}", file=sys.stderr)
                continue
    
    if not records:
        print(f"Nenhum record encontrado em {jsonl_path}")
        return
    
    # Obter todas as chaves únicas de todos os records
    all_keys = set()
    for record in records:
        all_keys.update(record.keys())
    
    # Ordenar as chaves para consistência
    fieldnames = sorted(all_keys)
    
    # Escrever CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for record in records:
            # Converter valores complexos para string
            row = {}
            for key in fieldnames:
                value = record.get(key)
                if isinstance(value, (dict, list)):
                    row[key] = json.dumps(value)
                elif value is None:
                    row[key] = ''
                else:
                    row[key] = value
            writer.writerow(row)
    
    print(f"✓ Convertido {len(records)} records: {jsonl_path.name} -> {csv_path.name}")


def main():
    """Função principal."""
    # Determinar diretório de output
    if len(sys.argv) > 1:
        output_dir = Path(sys.argv[1])
    else:
        output_dir = Path('output')
    
    # Criar diretório output se não existir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Encontrar todos os ficheiros JSONL na root dir
    root_dir = Path('.')
    root_jsonl_files = list(root_dir.glob('*.jsonl'))
    
    # Mover arquivos .jsonl da root para output
    moved_files = []
    for jsonl_file in root_jsonl_files:
        destination = output_dir / jsonl_file.name
        if jsonl_file != destination:  # Evitar mover para o mesmo lugar
            shutil.move(str(jsonl_file), str(destination))
            moved_files.append(destination)
            print(f"✓ Movido: {jsonl_file.name} -> {output_dir.name}/")
    
    # Encontrar todos os ficheiros JSONL no diretório output (incluindo os movidos)
    jsonl_files = list(output_dir.glob('*.jsonl'))
    
    if not jsonl_files:
        print(f"Nenhum ficheiro .jsonl encontrado em '{output_dir}' ou na root dir")
        print("Execute primeiro: tap-x-lightspeed --config config.json --catalog catalog.json | target-jsonl")
        sys.exit(1)
    
    # Converter cada JSONL para CSV
    for jsonl_path in jsonl_files:
        csv_path = jsonl_path.with_suffix('.csv')
        jsonl_to_csv(jsonl_path, csv_path)
    
    # Remover arquivos .jsonl após conversão
    removed_count = 0
    for jsonl_path in jsonl_files:
        try:
            jsonl_path.unlink()
            removed_count += 1
            print(f"✓ Removido: {jsonl_path.name}")
        except Exception as e:
            print(f"⚠ Erro ao remover {jsonl_path.name}: {e}", file=sys.stderr)
    
    print(f"\n✓ Conversão concluída! {len(jsonl_files)} ficheiro(s) convertido(s).")
    print(f"✓ {removed_count} ficheiro(s) .jsonl removido(s). Apenas CSVs mantidos.")


if __name__ == '__main__':
    main()

