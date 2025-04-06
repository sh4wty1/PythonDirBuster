import requests
from colored import fg

# Colors
purple = fg("purple_3")
green = fg("green")
red = fg("red")


def show_banner():
    print(
        "\n"
        + purple
        + r"""  
  _____       _   _                   _____  _      _               _   
 |  __ \     | | | |                 |  __ \(_)    | |             | |  
 | |__) |   _| |_| |__   ___  _ __   | |  | |_ _ __| |__  _   _ ___| |_ 
 |  ___/ | | | __| '_ \ / _ \| '_ \  | |  | | | '__| '_ \| | | / __| __|
 | |   | |_| | |_| | | | (_) | | | | | |__| | | |  | |_) | |_| \__ \ |_ 
 |_|    \__, |\__|_| |_|\___/|_| |_| |_____/|_|_|  |_.__/ \__,_|___/\__|
         __/ |                                                          
        |___/                                                           
"""
    )
    print(purple + "Coded by @nglshawty1 :)\n")
    print(
        purple
        + "This process might take a while depending on the size of the wordlist...\n"
    )


def format_url(url):
    if not url.startswith("http://") and not url.startswith("https://"):
        return "https://" + url
    return url


def run_dirbuster(target_url, wordlist_path="Subdomain.txt"):
    try:
        with open(wordlist_path, "r") as file:
            lines = file.read().splitlines()
    except FileNotFoundError:
        print(red + f"Wordlist '{wordlist_path}' not found.")
        return

    for word in lines:
        url = f"{target_url}/{word}"
        try:
            response = requests.get(url)
            if 200 <= response.status_code <= 299:
                print(green + "########################")
                print(green + f"{url} // status code: {response.status_code}")
                print(green + "########################")
            else:
                print(red + f"Offline: {url} (status {response.status_code})")
        except requests.RequestException:
            print(red + f"Error connecting to: {url}")


def main():
    show_banner()
    target = input("Enter the target URL -> ").strip()
    target = format_url(target)
    run_dirbuster(target)


if __name__ == "__main__":
    main()
    
