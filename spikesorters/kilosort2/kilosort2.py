from pathlib import Path
import os
import sys
import numpy as np
from typing import Union
import shutil

import spikeextractors as se
from ..basesorter import BaseSorter
from ..sorter_tools import _call_command_split


def check_if_installed(kilosort2_path: Union[str, None]):
    if kilosort2_path is None:
        return False
    assert isinstance(kilosort2_path, str)

    if kilosort2_path.startswith('"'):
        kilosort2_path = kilosort2_path[1:-1]
    kilosort2_path = str(Path(kilosort2_path).absolute())

    if (Path(kilosort2_path) / 'master_kilosort.m').is_file():
        return True
    else:
        return False


class Kilosort2Sorter(BaseSorter):
    """
    """

    sorter_name: str = 'kilosort2'
    kilosort2_path: Union[str, None] = os.getenv('KILOSORT2_PATH', None)
    installed = check_if_installed(kilosort2_path)

    _default_params = {
        'detect_threshold': 5,
        'car': True,
        'minFR': 0.1,
        'electrode_dimensions': None,
        'freq_min': 150,
        'sigmaMask': 30,
        'nPCs': 3
    }

    installation_mesg = """\nTo use Kilosort2 run:\n
        >>> git clone https://github.com/MouseLand/Kilosort2
    and provide the installation path by setting the KILOSORT2_PATH
    environment variables or using Kilosort2Sorter.set_kilosort2_path().\n\n

    More information on Kilosort2 at:
        https://github.com/MouseLand/Kilosort2
    """

    def __init__(self, **kargs):
        BaseSorter.__init__(self, **kargs)

    @staticmethod
    def set_kilosort2_path(kilosort2_path: str):
        Kilosort2Sorter.kilosort2_path = kilosort2_path
        Kilosort2Sorter.installed = check_if_installed(Kilosort2Sorter.kilosort2_path)
        try:
            print("Setting KILOSORT2_PATH environment variable for subprocess calls to:", kilosort2_path)
            os.environ["KILOSORT2_PATH"] = kilosort2_path
        except Exception as e:
            print("Could not set KILOSORT2_PATH environment variable:", e)

    def _setup_recording(self, recording, output_folder):
        source_dir = Path(Path(__file__).parent)
        p = self.params

        if not check_if_installed(Kilosort2Sorter.kilosort2_path):
            raise Exception(Kilosort2Sorter.installation_mesg)
        assert isinstance(Kilosort2Sorter.kilosort2_path, str)

        # prepare electrode positions
        electrode_dimensions = p['electrode_dimensions']
        if electrode_dimensions is None:
            electrode_dimensions = [0, 1]
        if 'group' in recording.get_channel_property_names():
            groups = recording.get_channel_groups()
        else:
            groups = [1] * recording.get_num_channels()
        if 'location' in recording.get_channel_property_names():
            positions = np.array(recording.get_channel_locations())
        else:
            print("'location' information is not found. Using linear configuration")
            positions = np.array(
                [[0, i_ch] for i_ch in range(recording.get_num_channels())])
            electrode_dimensions = [0, 1]

        # save binary file
        input_file_path = output_folder / 'recording'
        write_binary_int16_scale_if_needed(recording, input_file_path)

        if p['car']:
            use_car = 1
        else:
            use_car = 0

        # read the template txt files
        with (source_dir / 'kilosort2_master.m').open('r') as f:
            kilosort2_master_txt = f.read()
        with (source_dir / 'kilosort2_config.m').open('r') as f:
            kilosort2_config_txt = f.read()
        with (source_dir / 'kilosort2_channelmap.m').open('r') as f:
            kilosort2_channelmap_txt = f.read()

        # make substitutions in txt files
        kilosort2_master_txt = kilosort2_master_txt.format(
            kilosort2_path=str(
                Path(Kilosort2Sorter.kilosort2_path).absolute()),
            output_folder=str(output_folder),
            channel_path=str(
                (output_folder / 'kilosort2_channelmap.m').absolute()),
            config_path=str((output_folder / 'kilosort2_config.m').absolute()),
        )

        kilosort2_config_txt = kilosort2_config_txt.format(
            nchan=recording.get_num_channels(),
            sample_rate=recording.get_sampling_frequency(),
            dat_file=str((output_folder / 'recording.dat').absolute()),
            minFR=p['minFR'],
            freq_min=p['freq_min'],
            sigmaMask=p['sigmaMask'],
            kilo_thresh=p['detect_threshold'],
            use_car=use_car,
            nPCs=p['nPCs']
        )

        kilosort2_channelmap_txt = kilosort2_channelmap_txt.format(
            nchan=recording.get_num_channels(),
            sample_rate=recording.get_sampling_frequency(),
            xcoords=list(positions[:, electrode_dimensions[0]]),
            ycoords=list(positions[:, electrode_dimensions[1]]),
            kcoords=groups
        )

        for fname, txt in zip(['kilosort2_master.m', 'kilosort2_config.m',
                               'kilosort2_channelmap.m'],
                              [kilosort2_master_txt, kilosort2_config_txt,
                               kilosort2_channelmap_txt]):
            with (output_folder / fname).open('w') as f:
                f.write(txt)

        shutil.copy(str(source_dir.parent / 'kilosort_npy_utils' / 'writeNPY.m'), str(output_folder))
        shutil.copy(str(source_dir.parent / 'kilosort_npy_utils' / 'constructNPYheader.m'), str(output_folder))

    def _run(self, recording, output_folder):
        cmd = "matlab -nosplash -nodisplay -r 'run {}; quit;'".format(
            output_folder / 'kilosort2_master.m')
        if self.debug:
            print(cmd)
        if "win" in sys.platform:
            cmd_list = ['matlab', '-nosplash', '-nodisplay', '-wait',
                        '-r', 'run {}; quit;'.format(output_folder / 'kilosort2_master.m')]
        else:
            cmd_list = ['matlab', '-nosplash', '-nodisplay',
                        '-r', 'run {}; quit;'.format(output_folder / 'kilosort2_master.m')]

        # retcode = _run_command_and_print_output_split(cmd_list)
        _call_command_split(cmd_list)

    @staticmethod
    def get_result_from_folder(output_folder):
        sorting = se.KiloSortSortingExtractor(output_folder)
        return sorting


def write_binary_int16_scale_if_needed(recording: se.RecordingExtractor, save_path: Path, time_axis: int=0):
    if save_path.suffix == '':
        # when suffix is already raw/bin/dat do not change it.
        save_path = save_path.parent / (save_path.name + '.dat')

    traces = recording.get_traces()
    min_val = np.min(traces)
    max_val = np.max(traces)
    if (min_val < -2**15) or (max_val >= 2**15) or (not _isinteger(traces)):
        print('Rescaling data before converting to int16.')
        max_abs = np.max(np.abs([min_val, max_val]))
        # scale with a margin
        scale_factor = 2**14 / max_abs
        traces = traces * scale_factor
    traces = traces.astype('int16')
    if time_axis == 0:
        traces = traces.T
    with save_path.open('wb') as f:
        traces.tofile(f)

    return save_path


def _isinteger(x):
    return np.all(np.equal(np.mod(x, 1), 0))
