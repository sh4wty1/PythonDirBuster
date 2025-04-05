import requests
from colored import fg

# Cores
roxo = fg('purple_3')
verde = fg('green')
vermelho = fg('red')

def show_banner():
    print("\n" + roxo + r"""  
  _____       _   _                   _____  _      _               _   
 |  __ \     | | | |                 |  __ \(_)    | |             | |  
 | |__) |   _| |_| |__   ___  _ __   | |  | |_ _ __| |__  _   _ ___| |_ 
 |  ___/ | | | __| '_ \ / _ \| '_ \  | |  | | | '__| '_ \| | | / __| __|
 | |   | |_| | |_| | | | (_) | | | | | |__| | | |  | |_) | |_| \__ \ |_ 
 |_|    \__, |\__|_| |_|\___/|_| |_| |_____/|_|_|  |_.__/ \__,_|___/\__|
         __/ |                                                          
        |___/                                                           
""")
    print(roxo + "Coded by @nglshawty1 :)\n")
    print(roxo + "Esse processo pode demorar um pouco dependendo do tamanho da wordlist...\n")

def format_url(url):
    if not url.startswith("http://") and not url.startswith("https://"):
        return "https://" + url
    return url

def run_dirbuster(target_url, wordlist_path="Subdomain.txt"):
    try:
        with open(wordlist_path, 'r') as file:
            lines = file.read().splitlines()
    except FileNotFoundError:
        print(vermelho + f"Wordlist '{wordlist_path}' não encontrada.")
        return

    for word in lines:
        url = f"{target_url}/{word}"
        try:
            response = requests.get(url)
            if 200 <= response.status_code <= 299:
                print(verde + "########################")
                print(verde + f"{url} // status code: {response.status_code}")
                print(verde + "########################")
            else:
                print(vermelho + f"Offline: {url} (status {response.status_code})")
        except requests.RequestException:
            print(vermelho + f"Erro ao conectar: {url}")

def main():
    show_banner()
    target = input("Digite a URL alvo -> ").strip()
    target = format_url(target)
    run_dirbuster(target)

if __name__ == "__main__":
    main()
