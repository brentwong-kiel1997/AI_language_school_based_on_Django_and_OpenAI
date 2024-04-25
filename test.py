from transribe import Transcribe


url = 'https://www.youtube.com/watch?v=tb8dz6Rr0Vk'

test = Transcribe(url=url)

test.audio2text()

print(test.text_with_ts)
print(test.language)
print(test.title)
print(test.id)
print(test.duration)
print(test.transcript)