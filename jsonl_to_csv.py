#!/usr/bin/env python3
"""
Script para converter ficheiros JSONL (do target-jsonl) para CSV.
Uso: python jsonl_to_csv.py [diretório_output]
"""

import json
import csv
import sys
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
    
    if not output_dir.exists():
        print(f"Erro: Diretório '{output_dir}' não existe.", file=sys.stderr)
        sys.exit(1)
    
    # Encontrar todos os ficheiros JSONL
    jsonl_files = list(output_dir.glob('*.jsonl'))
    
    if not jsonl_files:
        print(f"Nenhum ficheiro .jsonl encontrado em '{output_dir}'")
        print("Execute primeiro: tap-r-lightspeed --config config.json --catalog catalog.json | target-jsonl")
        sys.exit(1)
    
    # Converter cada JSONL para CSV
    for jsonl_path in jsonl_files:
        csv_path = jsonl_path.with_suffix('.csv')
        jsonl_to_csv(jsonl_path, csv_path)
    
    print(f"\n✓ Conversão concluída! {len(jsonl_files)} ficheiro(s) convertido(s).")


if __name__ == '__main__':
    main()

