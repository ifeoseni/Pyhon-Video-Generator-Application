import subprocess  
cmds = [  
 ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=128x72', '-t', '1', '-vf', 'drawtext=text=''Test'':fontfile=''C\\:/Windows/Fonts/arial.ttf'':fontsize=12', 'test1.mp4'],  
 ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=128x72', '-t', '1', '-vf', 'drawtext=text=''Test'':fontfile=''C:/Windows/Fonts/arial.ttf'':fontsize=12', 'test2.mp4'],  
 ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=128x72', '-t', '1', '-vf', 'drawtext=text=''Test'':fontfile=C\\\\:/Windows/Fonts/arial.ttf:fontsize=12', 'test3.mp4']  
]  
for i, c in enumerate(cmds):  
  print(i, '---')  
  r = subprocess.run(c, capture_output=True, text=True)  
  print(r.returncode, r.stderr if r.returncode != 0 else 'ok') 
