import requests
from colored import fg
abc = fg('purple_3')
color = fg('green')
color2 = fg('red')
def Apresentation():    
    print("")
    print(abc + "  _____       _   _                   _____  _      _               _   ")
    print(abc + " |  __ \     | | | |                 |  __ \(_)    | |             | |  ")
    print(abc + " | |__) |   _| |_| |__   ___  _ __   | |  | |_ _ __| |__  _   _ ___| |_ ")
    print(abc + " |  ___/ | | | __| '_ \ / _ \| '_ \  | |  | | | '__| '_ \| | | / __| __|")
    print(abc + " | |   | |_| | |_| | | | (_) | | | | | |__| | | |  | |_) | |_| \__ \ |_ ")
    print(abc + " |_|    \__, |\__|_| |_|\___/|_| |_| |_____/|_|_|  |_.__/ \__,_|___/\__|")
    print(abc + "         __/ |                                                          ")
    print(abc + "        |___/                                                           ")
    print("")
    print(abc + "Coded by @nglshawty1 :)")
    print("")
    print(color2 + "Warning: You NEED to put the 'https://' part of the URL, otherwise, it will not work. Example:")
    print(color2 + "Incorrect: google.com")
    print(color2 + "Correct: https://google.com/")
    print(abc + "This can take really a long time due to the huge wordlist, so be patient lol...")
    print("")

def Main():
    Apresentation()
    file = open("Subdomain.txt")
    lines = file.readlines()
    target = input('Type your URL -> ')
    for word in lines:
        word = word.replace('\n', '')
        r = requests.get(target+word)
        if 200 <= r.status_code <= 299:
            print(color + "########################")
            print(color + word, "// status code:", r.status_code)
            print(color + "########################")
        else:
            print(color2 + "Offline")
Main()