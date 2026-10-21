"""Reviewed training examples for the small EN/ES media intent classifier.

No user transcripts are learned or stored. Evaluation phrases live in tests.
"""

MEDIA_PHRASES = {
    "open spotify": (
        "launch spotify", "start spotify", "open the spotify app", "bring up spotify",
        "launch the spotify application", "open spotify desktop",
        "abre spotify", "abrir spotify", "inicia spotify", "abre la aplicacion spotify",
        "quiero abrir spotify", "abre spotify desktop",
    ),
    "play music": (
        "start the music", "play some music", "resume the music", "resume playback",
        "start playing music", "continue playing", "put some music on", "play the song",
        "pon musica", "pon la musica", "reproduce musica", "reanuda la musica",
        "continua la reproduccion", "sigue reproduciendo", "pon una cancion",
        "reproduce la cancion", "quiero escuchar musica",
    ),
    "pause music": (
        "pause the music", "pause the song", "stop the music", "pause playback",
        "stop playing music", "pause it", "pause the audio", "pause the player",
        "pausa la musica", "pausa la cancion", "deten la musica", "para la musica",
        "pausa la reproduccion", "pon la musica en pausa", "deten la reproduccion",
        "pausa el reproductor", "pausa el audio",
    ),
    "next track": (
        "skip this song", "skip the track", "play the next song", "next song please",
        "go to the next track", "skip to the next song", "move to the next song",
        "pasa a la siguiente cancion", "siguiente cancion", "salta esta cancion",
        "pon la siguiente", "cambia a la siguiente pista", "avanza a la siguiente cancion",
        "pasa a la siguiente", "salta a la siguiente pista",
    ),
    "previous track": (
        "go back a song", "play the previous song", "previous song please",
        "go to the previous track", "back to the last song", "play the last track",
        "return to the previous song", "go back to the previous song",
        "vuelve a la cancion anterior", "pon la anterior", "cancion anterior",
        "regresa a la pista anterior", "retrocede una cancion", "pasa a la anterior",
        "reproduce la cancion anterior", "vuelve a la anterior",
    ),
    "volume up": (
        "increase the volume", "raise the volume", "make it louder", "turn it up",
        "turn up the music", "make the music louder", "raise the sound",
        "sube el volumen", "aumenta el volumen", "sube la musica", "mas volumen",
        "pon la musica mas fuerte", "haz que suene mas alto", "sube el sonido", "subir el volumen",
    ),
    "volume down": (
        "decrease the volume", "lower the volume", "make it quieter", "turn it down",
        "turn down the music", "make the music softer", "reduce the sound",
        "baja el volumen", "reduce el volumen", "baja la musica", "menos volumen",
        "pon la musica mas suave", "haz que suene mas bajo", "baja el sonido", "bajar el volumen",
    ),
    "mute": (
        "mute the sound", "mute the audio", "mute the volume", "silence the audio",
        "mute the speakers", "mute my computer", "toggle mute",
        "silencia el sonido", "silencia el audio", "silencia el volumen",
        "silencia los altavoces", "silencia la computadora", "activa el silencio",
    ),
}

NEGATIVE_PHRASES = (
    "open the music folder", "delete the song", "download music", "install spotify",
    "connect my spotify account", "play a specific album", "play jazz",
    "what song is this", "what is playing", "how do I pause music", "I like this song",
    "the music is paused", "Spotify is open", "set an alarm", "close the player",
    "restart the song", "seek forward", "turn off the computer", "change the music",
    "change the volume", "stop", "continue", "open notepad", "open calculator",
    "abre la carpeta musica", "elimina la cancion", "descarga musica", "instala spotify",
    "conecta mi cuenta spotify", "pon un album especifico", "pon jazz",
    "que cancion es esta", "que esta sonando", "como pauso la musica",
    "me gusta esta cancion", "la musica esta pausada", "spotify esta abierto",
    "pon una alarma", "cierra el reproductor", "reinicia la cancion",
    "adelanta la cancion", "apaga la computadora", "cambia la musica",
    "cambia el volumen", "detente", "continua", "abre bloc de notas", "abre calculadora",
)
