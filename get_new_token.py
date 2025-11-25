#!/usr/bin/env python3
"""
Script para obter um novo refresh token do Lightspeed X-Series.
Siga os passos da documentação: https://x-series-api.lightspeedhq.com/docs/authorization
"""

import json
import requests
from urllib.parse import urlencode

# Configurações
DOMAIN_PREFIX = "mariooptiply"
CLIENT_ID = "uyGcZI1Ub1thuhiLmRKC3FAvWOLMd2l3"
CLIENT_SECRET = "VYCM2AW4JtlBMqSLAdAHbsLZSWYgan6z"
REDIRECT_URI = "https://callback.oauth.optiply.com"  # Ajuste conforme configurado na sua app
SCOPE = "audit:read billing:partner_subscription:read billing:partner_subscription:write business_rules:read business_rules:write channels:read consignments:read consignments:write:inventory_count consignments:write:stock_order consignments:write:stock_transfer customers:read customers:write custom_fields:read custom_fields:write fulfillments:read fulfillments:write gift_cards:read gift_cards:write:issue gift_cards:write:redeem inventory:read outlets:read payments:read payment_types:read products:read products:read:price_books products:write products:write:price_books promotions:read promotions:write register:close register:open registers:read remote_rules:read remote_rules:write retailer:read sales:read sales:write serial_numbers:read serial_numbers:write services:read services:write store_credits:read store_credits:write:issue suppliers:read suppliers:write taxes:read taxes:write users:read users:write webhooks"  # Ajuste conforme necessário

def get_authorization_url():
    """Gera a URL de autorização para o utilizador autorizar a aplicação."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": "random_state_string_12345",  # Deve ser único e aleatório (mínimo 8 caracteres)
        "scope": SCOPE
    }
    
    url = f"https://secure.retail.lightspeed.app/connect?{urlencode(params)}"
    return url

def exchange_code_for_token(authorization_code, domain_prefix):
    """Troca o código de autorização por access token e refresh token."""
    url = f"https://{domain_prefix}.retail.lightspeed.app/api/1.0/token"
    
    data = {
        "code": authorization_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }
    
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()

def refresh_access_token(refresh_token, domain_prefix):
    """Atualiza o access token usando o refresh token."""
    url = f"https://{domain_prefix}.retail.lightspeed.app/api/1.0/token"
    
    data = {
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token"
    }
    
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    print("=" * 60)
    print("Lightspeed X-Series - Obter Novo Token")
    print("=" * 60)
    print("\nOpção 1: Obter novo token (fluxo completo OAuth)")
    print("Opção 2: Tentar refresh com token existente")
    
    choice = input("\nEscolha (1 ou 2): ").strip()
    
    if choice == "1":
        print("\n" + "=" * 60)
        print("PASSO 1: Autorizar a aplicação")
        print("=" * 60)
        auth_url = get_authorization_url()
        print(f"\nAbra este URL no seu navegador:")
        print(f"\n{auth_url}\n")
        print("Depois de autorizar, será redirecionado para:")
        print(f"{REDIRECT_URI}?code=<AUTHORIZATION_CODE>&domain_prefix={DOMAIN_PREFIX}&state=...")
        
        auth_code = input("\nCole o código de autorização (code) da URL: ").strip()
        domain_from_callback = input(f"Cole o domain_prefix da URL (ou pressione Enter para usar '{DOMAIN_PREFIX}'): ").strip() or DOMAIN_PREFIX
        
        print("\n" + "=" * 60)
        print("PASSO 2: Trocar código por tokens")
        print("=" * 60)
        
        try:
            token_data = exchange_code_for_token(auth_code, domain_from_callback)
            
            print("\n✓ Tokens obtidos com sucesso!")
            print("\nToken data:")
            print(json.dumps(token_data, indent=2))
            
            # Salvar no config.json
            config = {
                "domain_prefix": token_data.get("domain_prefix", domain_from_callback),
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": token_data["refresh_token"],
                "access_token": token_data["access_token"],
                "expires": token_data.get("expires"),
                "expires_in": token_data.get("expires_in"),
                "scope": token_data.get("scope"),
                "token_type": token_data.get("token_type", "Bearer")
            }
            
            save = input("\nGuardar no config.json? (s/n): ").strip().lower()
            if save == "s":
                with open("config.json", "w") as f:
                    json.dump(config, f, indent=4)
                print("✓ Config guardado em config.json")
            
        except requests.exceptions.HTTPError as e:
            print(f"\n✗ Erro ao obter tokens: {e}")
            if e.response:
                print(f"Resposta: {e.response.text}")
    
    elif choice == "2":
        print("\n" + "=" * 60)
        print("Tentar refresh com token existente")
        print("=" * 60)
        
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
            
            refresh_token = config.get("refresh_token")
            domain_prefix = config.get("domain_prefix", DOMAIN_PREFIX)
            
            if not refresh_token:
                print("✗ refresh_token não encontrado no config.json")
                exit(1)
            
            print(f"Usando refresh_token: {refresh_token[:30]}...")
            print(f"Domain prefix: {domain_prefix}")
            
            token_data = refresh_access_token(refresh_token, domain_prefix)
            
            print("\n✓ Token atualizado com sucesso!")
            print("\nNovo token data:")
            print(json.dumps(token_data, indent=2))
            
            # Atualizar config.json
            config["access_token"] = token_data["access_token"]
            config["refresh_token"] = token_data["refresh_token"]
            config["expires"] = token_data.get("expires")
            config["expires_in"] = token_data.get("expires_in")
            
            with open("config.json", "w") as f:
                json.dump(config, f, indent=4)
            print("\n✓ Config.json atualizado")
            
        except requests.exceptions.HTTPError as e:
            print(f"\n✗ Erro ao fazer refresh: {e}")
            if e.response:
                print(f"Resposta: {e.response.text}")
                if e.response.status_code == 400:
                    print("\n⚠ O refresh token pode estar expirado ou inválido.")
                    print("   Precisa obter um novo token usando a Opção 1.")
        except FileNotFoundError:
            print("✗ config.json não encontrado")
    else:
        print("Opção inválida")

