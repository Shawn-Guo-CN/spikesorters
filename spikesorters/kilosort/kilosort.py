from pathlib import Path
import os
import sys
from typing import Union
import shutil
import numpy as np

import spikeextractors as se
from ..basesorter import BaseSorter
from ..sorter_tools import _call_command_split


def check_if_installed(kilosort_path: Union[str, None]):
    if kilosort_path is None:
        return False
    assert isinstance(kilosort_path, str)

    if kilosort_path.startswith('"'):
        kilosort_path = kilosort_path[1:-1]
    kilosort_path = str(Path(kilosort_path).absolute())

    if (Path(kilosort_path) / 'preprocessData.m').is_file():
        return True
    else:
        return False


class KilosortSorter(BaseSorter):
    """
    """

    sorter_name: str = 'kilosort'
    kilosort_path: Union[str, None] = os.getenv('KILOSORT_PATH', None)
    installed = check_if_installed(kilosort_path)

    _default_params = {
        'detect_threshold': 6,
        'car': True,
        'useGPU': True,
        'electrode_dimensions': None,
        'freq_min': 300,
        'freq_max': 6000
    }

    installation_mesg = """\nTo use Kilosort run:\n
        >>> git clone https://github.com/cortex-lab/KiloSort
    and provide the installation path by setting the KILOSORT_PATH
    environment variables or using KilosortSorter.set_kilosort_path().\n\n

    More information on KiloSort at:
        https://github.com/cortex-lab/KiloSort
    """

    def __init__(self, **kargs):
        BaseSorter.__init__(self, **kargs)

    @staticmethod
    def set_kilosort_path(kilosort_path: str):
        KilosortSorter.kilosort_path = kilosort_path
        KilosortSorter.installed = check_if_installed(KilosortSorter.kilosort_path)
        try:
            print("Setting KILOSORT_PATH environment variable for subprocess calls to:", kilosort_path)
            os.environ["KILOSORT_PATH"] = kilosort_path
        except Exception as e:
            print("Could not set KILOSORT_PATH environment variable:", e)

    def _setup_recording(self, recording, output_folder):
        source_dir = Path(__file__).parent
        p = self.params

        if not check_if_installed(KilosortSorter.kilosort_path):
            raise Exception(KilosortSorter.installation_mesg)
        assert isinstance(KilosortSorter.kilosort_path, str)

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
        write_binary_dat_format_autoscale(recording, input_file_path, dtype='int16')

        # set up kilosort config files and run kilosort on data
        with (source_dir / 'kilosort_master.m').open('r') as f:
            kilosort_master_txt = f.read()
        with (source_dir / 'kilosort_config.m').open('r') as f:
            kilosort_config_txt = f.read()
        with (source_dir / 'kilosort_channelmap.m').open('r') as f:
            kilosort_channelmap_txt = f.read()

        nchan = recording.get_num_channels()
        Nfilt = (nchan // 32) * 32 * 8
        if Nfilt == 0:
            Nfilt = nchan * 8
        Nt = 128 * 1024 + 64

        if p['useGPU']:
            useGPU = 1
        else:
            useGPU = 0

        if p['car']:
            use_car = 1
        else:
            use_car = 0

        # make substitutions in txt files
        kilosort_master_txt = kilosort_master_txt.format(
            kilosort_path=str(
                Path(KilosortSorter.kilosort_path).absolute()),
            output_folder=str(output_folder),
            channel_path=str(
                (output_folder / 'kilosort_channelmap.m').absolute()),
            config_path=str((output_folder / 'kilosort_config.m').absolute()),
            useGPU=useGPU, 
        )
        
        kilosort_config_txt = kilosort_config_txt.format(
            nchanTOT=recording.get_num_channels(),
            nchan=recording.get_num_channels(),
            sample_rate=recording.get_sampling_frequency(),
            dat_file=str((output_folder / 'recording.dat').absolute()),
            Nfilt=Nfilt,
            Nt=Nt,
            kilo_thresh=p['detect_threshold'],
            use_car=use_car,
            freq_min=p['freq_min'],
            freq_max=p['freq_max']
        )

        kilosort_channelmap_txt = kilosort_channelmap_txt.format(
            nchan=recording.get_num_channels(),
            sample_rate=recording.get_sampling_frequency(),
            xcoords=list(positions[:, electrode_dimensions[0]]),
            ycoords=list(positions[:, electrode_dimensions[1]]),
            kcoords=groups
        )

        for fname, value in zip(['kilosort_master.m', 'kilosort_config.m',
                                 'kilosort_channelmap.m'],
                                [kilosort_master_txt, kilosort_config_txt,
                                 kilosort_channelmap_txt]):
            with (output_folder / fname).open('w') as f:
                f.writelines(value)

        shutil.copy(str(source_dir.parent / 'kilosort_npy_utils' / 'writeNPY.m'), str(output_folder))
        shutil.copy(str(source_dir.parent / 'kilosort_npy_utils' / 'constructNPYheader.m'), str(output_folder))

    def _run(self, recording, output_folder):
        cmd = "matlab -nosplash -nodisplay -r 'run {}; quit;'".format(output_folder / 'kilosort_master.m')
        if self.debug:
            print(cmd)
        if "win" in sys.platform:
            cmd_list = ['matlab', '-nosplash', '-nodisplay', '-wait',
                        '-r','run {}; quit;'.format(output_folder / 'kilosort_master.m')]
        else:
            cmd_list = ['matlab', '-nosplash', '-nodisplay',
                        '-r', 'run {}; quit;'.format(output_folder / 'kilosort_master.m')]

        # retcode = _run_command_and_print_output_split(cmd_list)
        _call_command_split(cmd_list)

    @staticmethod
    def get_result_from_folder(output_folder):
        sorting = se.KiloSortSortingExtractor(output_folder)
        return sorting


def write_binary_dat_format_autoscale(recording, save_path, time_axis=0, dtype=None, chunksize=None):
    '''Saves the traces of a recording extractor in binary .dat format.

    Parameters
    ----------
    recording: RecordingExtractor
        The recording extractor object to be saved in .dat format
    save_path: str
        The path to the file.
    time_axis: 0 (default) or 1
        If 0 then traces are transposed to ensure (nb_sample, nb_channel) in the file.
        If 1, the traces shape (nb_channel, nb_sample) is kept in the file.
    dtype: dtype
        Type of the saved data. Default float32
    chunksize: None or int
        If not None then the copy done by chunk size.
        Thi avoid to much memory consumption for big files.
    Returns
    -------
    '''
    save_path = Path(save_path)
    if save_path.suffix == '':
        # when suffix is already raw/bin/dat do not change it.
        save_path = save_path.parent / (save_path.name + '.dat')

    if chunksize is None:
        traces = recording.get_traces()
        scale_factor = 2**14 / np.max(np.abs(traces))
        traces = traces * scale_factor

        if dtype is not None:
            traces = traces.astype(dtype)
        if time_axis == 0:
            traces = traces.T
        with save_path.open('wb') as f:
            traces.tofile(f)
    else:
        raise Exception('Cannot auto scale with chunks')
        assert time_axis ==0, 'chunked writting work only with time_axis 0'
        n_sample = recording.get_num_frames()
        n_chan = recording.get_num_channels()
        n_chunk = n_sample // chunksize
        if n_sample % chunksize > 0:
            n_chunk += 1
        with save_path.open('wb') as f:
            for i in range(n_chunk):
                traces = recording.get_traces(start_frame=i*chunksize,
                                              end_frame=min((i+1)*chunksize, n_sample))
                if dtype is not None:
                    traces = traces.astype(dtype)
                if time_axis == 0:
                    traces = traces.T
                f.write(traces.tobytes())
    return save_path