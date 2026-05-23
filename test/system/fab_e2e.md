# End to end test (compares gerbers and BOMs)

 - create `/tmp/kikit-e2e.yaml`. Example contents:

 ```
projects:
  - name: c-uc_highpower
    path: ~/meteo/ss/rf-boards/c-uc_highpower/c-uc_highpower.kicad_pcb
    cmd: jlcpcb
    args: [--assembly, --autoname, --no-drc]

  - name: comms_board
    path: ~/meteo/ss/breakout/comms_board/comms_board.kicad_pcb
    cmd: jlcpcb
    args: [--assembly, --autoname, --no-drc]

  - name: PA_quad_v5
    path: ~/meteo/ss/rf-boards/c-sspa/PA_quad_v5/PA_quad_v5.kicad_pcb
    cmd: gatema
    args: [--no-drc]
 ```
  - run `./test/system/fab_e2e.py snapshot kikit-e2e.yaml /tmp/kikit-e2e-snap`
    - this creates PNGs from gerbers + saves CSV files (bom+pos) to `/tmp/kikit-e2e-snap`
  - perform changes to kikit
  - run `./test/system/fab_e2e.py compare kikit-e2e.yaml /tmp/kikit-e2e-snap`
    - this compares the output images and CSVs are the same as before