from pcbnewTransition import pcbnew
import os
import shutil
from pcbnewTransition.pcbnew import GENDRILL_WRITER_BASE
from pathlib import Path
from kikit.export import gerberImpl, exportSettingsOSHPark, fullGerberPlotPlan
from kikit.fab.common import ensurePassingDrc, expandNameTemplate, refillAllZones


exportSettingsGatema = {
    "UseGerberProtelExtensions": True,
    "UseAuxOrigin": True,
    "ExcludeEdgeLayer": True,
    "MinimalHeader": False,
    "NoSuffix": False,
    "MergeNPTH": False,
    "ZerosFormat": GENDRILL_WRITER_BASE.DECIMAL_FORMAT,
    "SubstractMaskFromSilk": True
}

extensionRenameTable = [
    (".gtl", ".top"),
    (".gbl", ".bot"),
    ("-PTH.drl", ".pth"),
    ("-NPTH.drl", ".mill"),
    (".gm1", ".dim"),
    (".g2", ".in2"),
    (".g3", ".in3"),
    (".gbs", ".smb"),
    (".gts", ".smt"),
    (".gbp", ".pastebot"),
    (".gtp", ".pastetop"),
    (".gbo", ".plb"),
    (".gto", ".plt"),
]

def exportGatema(board, outputdir, nametemplate, drc):
    """
    Prepare fabrication files for Gatema
    """
    loadedBoard = pcbnew.LoadBoard(board)
    Path(outputdir).mkdir(parents=True, exist_ok=True)

    refillAllZones(loadedBoard)
    ensurePassingDrc(loadedBoard)

    gerberdir = os.path.join(outputdir, "gerber")
    shutil.rmtree(gerberdir, ignore_errors=True)
    gerberImpl(board, gerberdir, board=loadedBoard, plot_plan=fullGerberPlotPlan, settings=exportSettingsGatema)

    # Rename files according to Gatema requirements
    # https://www.gatemapcb.cz/wp-content/uploads/2023/08/oznaceni-vrstev.pdf
    for old, new in extensionRenameTable:
        oldFile = list(Path(gerberdir).glob(f"*{old}"))
        # Can be empty for two layer boards and .g2/.g3
        assert len(oldFile) <= 1, f"Multiple files found for extension {old}"
        for file in oldFile:
            file.rename(file.with_suffix(new))

    boardName = os.path.basename(board.replace(".kicad_pcb", ""))
    archiveName = expandNameTemplate(nametemplate, boardName + "-gerbers", loadedBoard)
    shutil.make_archive(os.path.join(outputdir, archiveName), "zip", outputdir, "gerber")
