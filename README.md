# AI language School Project with Django and OpenAI
You can find the example of the website hosted on pythonanywhere at following link,[Example]([https://brentwmq.pythonanywhere.com/](https://brentwmq.pythonanywhere.com/learning_material/loeB4hyK9T8/English))

## Introduction
This is a project developed by me, Brent Wong([Linkedin Profile](https://www.linkedin.com/in/mingqianwangbrent987614198/))

The main purpose of this project is to use AI to make learning materials based on short news reports from YouTube.
For more detailed information, please look at the project breakdown section.

### Collaboration
If you like to discuss collaboration, please contact me via email [brentwang1997@gmail.com](brentwang1997@gmail.com).

### Donation
If you find this useful and would like to support my work,
you can make some donation via this [PayPal link](https://paypal.me/brentwmq?country.x=DE&locale.x=en_US
)

### Disclaimer
**Please do not share the YouTube videos downloaded using this project.**

Once the video is transcribed, the program will delete the original video and audio.
If you need to share the videos along with the materials, please share them via 
**YouTube link** or add the original video via **YouTube Embedding function**.
Make sure each time the videos are played, the original creators can benefit from those views.

The materials generated from the programming are considered as **commentaries**.

## Website Guide



![Screenshot from 2024-08-07 13-30-23](https://github.com/user-attachments/assets/2ec48428-6a14-48f7-a25c-028ffd00b5cf)


## Use case 1
You can use the website to transcibe news videos from youtube via the url input link.

**Important notes**

1. The download function is realized via [yt_dlp](https://github.com/yt-dlp/yt-dlp) and it is often likely not working due to YouTube changing their website features. Please check out the third party package website for updates. I will not update this part of code constantly.
  
2. You'll need your own OpenAI API key for set up your own website as well.
   
3. Please find the relevant code under following path. 'bals/main_app/utils.py'

![image](https://github.com/user-attachments/assets/af4854e3-2401-4e94-8170-62278040e868)

## Use case 2 
You can also just click on the existing materials from the dataset.
For now only English and Ukrianian are supported as native languages. If you wanna add more, please find the file at following path. 'bals/main_app/forms.py'

![image](https://github.com/user-attachments/assets/93f30bc2-b512-47cc-beef-f0573f9ceb52)

![image](https://github.com/user-attachments/assets/fa0e8ce5-ef91-44ee-bc10-f0825cca9dd3)



