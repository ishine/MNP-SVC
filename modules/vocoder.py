import os

import onnxruntime
import numpy as np
import torch
import torch.nn.functional as F
import yaml

from modules.common import DotDict, complex_mul_in_real_3d

from modules.stft import STFT


def load_model(
        model_path,
        device='cpu'):
    config_file = os.path.join(os.path.split(model_path)[0], 'config.yaml')
    print('Loading config file from: ' + config_file)
    with open(config_file, "r") as config:
        args = yaml.safe_load(config)
    args = DotDict(args)
    
    # load model
    model = None
    if args.model.type == 'CombSubMinimumNoisedPhase':
        # model = CombSubMinimumNoisedPhase_export(
        model = CombSubMinimumNoisedPhase(
            sampling_rate=args.data.sampling_rate,
            block_size=args.data.block_size,
            win_length=args.model.win_length,
            n_unit=args.data.encoder_out_channels,
            n_hidden_channels=args.model.units_hidden_channels,
            n_spk=args.model.n_spk,
            use_speaker_embed=args.model.use_speaker_embed,
            use_embed_conv=not args.model.no_use_embed_conv,
            spk_embed_channels=args.data.spk_embed_channels,
            f0_input_variance=args.model.f0_input_variance,
            f0_offset_size_downsamples=args.model.f0_offset_size_downsamples,
            noise_env_size_downsamples=args.model.noise_env_size_downsamples,
            harmonic_env_size_downsamples=args.model.harmonic_env_size_downsamples,
            use_harmonic_env=args.model.use_harmonic_env,
            use_noise_env=args.model.use_noise_env,
            noise_to_harmonic_phase=args.model.noise_to_harmonic_phase,
            add_noise=args.model.add_noise,
            use_phase_offset=args.model.use_phase_offset,
            use_f0_offset=args.model.use_f0_offset,
            no_use_noise=args.model.no_use_noise,
            use_short_filter=args.model.use_short_filter,
            use_noise_short_filter=args.model.use_noise_short_filter,
            use_pitch_aug=args.model.use_pitch_aug,
            noise_seed=args.model.noise_seed,
            device=device,
            # export_onnx=True,
            )
        
    elif args.model.type == 'NMPSFHiFi':
        model = NMPSFHiFi(
            sampling_rate=args.data.sampling_rate,
            block_size=args.data.block_size,
            win_length=args.model.win_length,
            n_unit=args.data.encoder_out_channels,
            n_hidden_channels=args.model.units_hidden_channels,
            n_spk=args.model.n_spk,
            use_speaker_embed=args.model.use_speaker_embed,
            use_embed_conv=not args.model.no_use_embed_conv,
            spk_embed_channels=args.data.spk_embed_channels,
            f0_input_variance=args.model.f0_input_variance,
            f0_offset_size_downsamples=args.model.f0_offset_size_downsamples,
            noise_env_size_downsamples=args.model.noise_env_size_downsamples,
            harmonic_env_size_downsamples=args.model.harmonic_env_size_downsamples,
            use_harmonic_env=args.model.use_harmonic_env,
            use_noise_env=args.model.use_noise_env,
            noise_to_harmonic_phase=args.model.noise_to_harmonic_phase,
            add_noise=args.model.add_noise,
            use_f0_offset=args.model.use_f0_offset,
            use_short_filter=args.model.use_short_filter,
            use_noise_short_filter=args.model.use_noise_short_filter,
            use_pitch_aug=args.model.use_pitch_aug,
            nsf_hifigan_in=args.model.nsf_hifigan.num_mels,
            nsf_hifigan_h=args.model.nsf_hifigan,
            noise_seed=args.model.noise_seed,
            )
            
    else:
        raise ValueError(f" [x] Unknown Model: {args.model.type}")
    
    print(' [Loading] ' + model_path)
    ckpt = torch.load(model_path, map_location=torch.device(device), weights_only=True)
    model.to(device)
    if 'model' in ckpt:
        ckpt = ckpt['model']
    else:
        ckpt = ckpt
    model.load_state_dict(ckpt, strict=False)
    model.eval()
    
    if args.model.use_speaker_embed:
        spk_info_path = os.path.join(os.path.split(model_path)[0], 'spk_info.npz')
        if os.path.isfile(spk_info_path):
            spk_info = np.load(spk_info_path, allow_pickle=True)
        else:
            print(' [Warning] spk_info.npz not found but model seems to setup with speaker embed')
            spk_info = None
    else:
        spk_info = None
    
    return model, args, spk_info


def load_onnx_model(
            model_path,
            providers=['CPUExecutionProvider'],
            device='cpu'):
    config_file = os.path.join(os.path.split(model_path)[0], 'config.yaml')
    with open(config_file, "r") as config:
        args = yaml.safe_load(config)
    args = DotDict(args)
    
    sess = onnxruntime.InferenceSession(
        model_path,
        providers=providers)
    
    # load model
    model = sess
    
    if args.model.use_speaker_embed:
        spk_info_path = os.path.join(os.path.split(model_path)[0], 'spk_info.npz')
        if os.path.isfile(spk_info_path):
            spk_info = np.load(spk_info_path, allow_pickle=True)
        else:
            print(' [Warning] spk_info.npz not found but model seems to setup with speaker embed')
            spk_info = None
    else:
        spk_info = None
    
    return model, args, spk_info


class CombSubMinimumNoisedPhaseStackOnly(torch.nn.Module):
    def __init__(self, 
            n_unit=256,
            n_hidden_channels=256):
        super().__init__()

        print(' [DDSP Model] Minimum-Phase harmonic Source Combtooth Subtractive Synthesiser (u2c stack only)')
        
        from .unit2control import Unit2ControlStackOnly
        self.unit2ctrl = Unit2ControlStackOnly(n_unit,
                                                n_hidden_channels=n_hidden_channels,
                                                conv_stack_middle_size=32)
        
    def forward(self, units_frames, **kwargs):
        '''
            units_frames: B x n_frames x n_unit
            f0_frames: B x n_frames x 1
            volume_frames: B x n_frames x 1 
            spk_id: B x 1
        '''
        
        return self.unit2ctrl(units_frames)


class CombSubMinimumNoisedPhase(torch.nn.Module):
    def __init__(self, 
            sampling_rate,
            block_size,
            win_length,
            n_unit=256,
            n_hidden_channels=256,
            n_spk=1,
            use_speaker_embed=True,
            use_embed_conv=True,
            spk_embed_channels=256,
            f0_input_variance=0.1,
            f0_offset_size_downsamples=1,
            noise_env_size_downsamples=4,
            harmonic_env_size_downsamples=4,
            use_harmonic_env=False,
            use_noise_env=True,
            use_add_noise_env=True,
            noise_to_harmonic_phase=False,
            add_noise=False,
            use_phase_offset=False,
            use_f0_offset=False,
            no_use_noise=False,
            use_short_filter=False,
            use_noise_short_filter=False,
            use_pitch_aug=False,
            noise_seed=289,
            onnx_unit2ctrl=None,
            export_onnx=False,
            device=None):
        super().__init__()

        print(' [DDSP Model] Minimum-Phase harmonic Source Combtooth Subtractive Synthesiser')
        
        # device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # params
        self.register_buffer("sampling_rate", torch.tensor(sampling_rate))
        self.register_buffer("block_size", torch.tensor(block_size))
        self.register_buffer("win_length", torch.tensor(win_length))
        self.register_buffer("window", torch.hann_window(win_length))
        self.register_buffer("f0_input_variance", torch.tensor(f0_input_variance))
        self.register_buffer("f0_offset_size_downsamples", torch.tensor(f0_offset_size_downsamples))
        self.register_buffer("noise_env_size_downsamples", torch.tensor(noise_env_size_downsamples))
        self.register_buffer("harmonic_env_size_downsamples", torch.tensor(harmonic_env_size_downsamples))
        self.register_buffer("use_harmonic_env", torch.tensor(use_harmonic_env))
        self.register_buffer("use_noise_env", torch.tensor(use_noise_env))
        self.register_buffer("use_add_noise_env", torch.tensor(use_add_noise_env))
        self.register_buffer("noise_to_harmonic_phase", torch.tensor(noise_to_harmonic_phase))
        # self.register_buffer("add_noise", torch.tensor(add_noise))
        self.register_buffer("use_f0_offset", torch.tensor(use_f0_offset))
        self.register_buffer("use_speaker_embed", torch.tensor(use_speaker_embed))
        self.register_buffer("use_embed_conv", torch.tensor(use_embed_conv))
        self.register_buffer("noise_seed", torch.tensor(noise_seed))
        
        if use_short_filter or use_noise_short_filter:
            self.register_buffer("window_s", torch.hann_window(16))
        
        if add_noise is None:
            self.add_noise = add_noise
        else:
            self.register_buffer("add_noise", torch.tensor(add_noise))
        
        if use_phase_offset is None:
            self.use_phase_offset = use_phase_offset
        else:
            self.register_buffer("use_phase_offset", torch.tensor(use_phase_offset))

        self.pred_filter_size = win_length // 2 + 1
        
        self.use_noise = not no_use_noise
        
        
        #Unit2Control
        split_map = {
        }
        if self.use_noise:
            if use_noise_env:
                split_map['noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        if use_harmonic_env:
            split_map['harmonic_envelope_magnitude'] = block_size//harmonic_env_size_downsamples
        if use_f0_offset:
            split_map['f0_offset'] = block_size//f0_offset_size_downsamples
        if add_noise:
            split_map['add_noise_magnitude'] = self.pred_filter_size
            split_map['add_noise_phase'] = self.pred_filter_size
            if use_add_noise_env:
                split_map['add_noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        if use_phase_offset:
            split_map['phase_offset'] = self.pred_filter_size
        if use_short_filter:
            # split_map['short_harmonic_magnitude'] = (512//4)*(16//2 + 1)
            # split_map['short_harmonic_phase'] = (512//4)*(16//2 + 1)
            split_map['short_harmonic_magnitude'] = self.pred_filter_size * 4
            split_map['short_harmonic_phase'] = self.pred_filter_size * 4
        if self.use_noise:
            if use_noise_short_filter:
                split_map['short_noise_magnitude'] = self.pred_filter_size * 4
                split_map['short_noise_phase'] = self.pred_filter_size * 4
                
        split_map['harmonic_magnitude'] = self.pred_filter_size * 4
        split_map['harmonic_phase'] = self.pred_filter_size * 4
        split_map['noise_magnitude'] = self.pred_filter_size * 4
        split_map['noise_phase'] = self.pred_filter_size * 4
                
            
        self.use_short_filter = use_short_filter
        self.use_noise_short_filter = use_noise_short_filter
            
        
        if onnx_unit2ctrl is not None:
            from .unit2control import Unit2ControlGE2E_onnx
            self.unit2ctrl = Unit2ControlGE2E_onnx(onnx_unit2ctrl, split_map)
        elif export_onnx:
            from .unit2control import Unit2ControlGE2E_export
            self.unit2ctrl = Unit2ControlGE2E_export(n_unit, spk_embed_channels, split_map,
                                            n_hidden_channels=n_hidden_channels,
                                            n_spk=n_spk,
                                            use_pitch_aug=use_pitch_aug,
                                            use_spk_embed=use_speaker_embed,
                                            use_embed_conv=use_embed_conv,
                                            embed_conv_channels=64, conv_stack_middle_size=32)
        else:
            from .unit2control import Unit2ControlGE2E
            self.unit2ctrl = Unit2ControlGE2E(n_unit, spk_embed_channels, split_map,
                                            n_hidden_channels=n_hidden_channels,
                                            n_spk=n_spk,
                                            use_pitch_aug=use_pitch_aug,
                                            use_spk_embed=use_speaker_embed,
                                            use_embed_conv=use_embed_conv,
                                            embed_conv_channels=64, conv_stack_middle_size=32)
        
        # generate static noise
        self.gen = torch.Generator()
        self.gen.manual_seed(noise_seed)
        static_noise_t = (torch.rand([
            win_length*127  # about 5.9sec when sampling_rate=44100 and win_length=2048
        ], generator=self.gen)*2.0-1.0)
        # if self.noise_to_harmonic_phase:
        #     dump = torch.zeros_like(static_noise_t)
        #     dump_samples = int(sampling_rate / 300.0)    # samples of 300Hz
        #     dump[:dump_samples] = torch.linspace(1.0, 0.0, dump_samples) ** 2.
        #     static_noise_t *= dump
        self.register_buffer('static_noise_t', static_noise_t)

        if add_noise:
            static_add_noise_t = (torch.rand([
            win_length*127  # about 5.9sec when sampling_rate=44100 and win_length=2048
            ], generator=self.gen)*2.0-1.0)
            self.register_buffer('static_add_noise_t', static_add_noise_t)
        
        # generate minimum-phase windowed sinc signal for harmonic source
        ## TODO: functional
        minphase_wsinc_w = 0.5 - 1/sampling_rate
        phase = torch.linspace(-(win_length*minphase_wsinc_w-1), win_length*minphase_wsinc_w, win_length)
        windowed_sinc = torch.sinc(
                phase
        ) * torch.blackman_window(win_length)
        log_freq_windowed_sinc = torch.log(torch.fft.fft(
            F.pad(windowed_sinc, (win_length//2, win_length//2)),
            n = win_length*2,
        ) + 1e-7)
        ceps_windowed_sinc = torch.fft.ifft(torch.cat([
            log_freq_windowed_sinc[:log_freq_windowed_sinc.shape[0]//2+1],
            torch.flip(log_freq_windowed_sinc[1:log_freq_windowed_sinc.shape[0]//2], (0,))
        ]))
        ceps_windowed_sinc.imag[0] *= -1.
        ceps_windowed_sinc.real[1:ceps_windowed_sinc.shape[0]//2] *= 2.
        ceps_windowed_sinc.imag[1:ceps_windowed_sinc.shape[0]//2] *= -2.
        ceps_windowed_sinc.imag[ceps_windowed_sinc.shape[0]//2] *= -1.
        ceps_windowed_sinc[ceps_windowed_sinc.shape[0]//2+1:] = 0.
        
        static_freq_minphase_wsinc = torch.fft.rfft( torch.fft.ifft(
            torch.exp(torch.fft.fft(ceps_windowed_sinc))
            ).real.roll(ceps_windowed_sinc.shape[0]//2-1)[:ceps_windowed_sinc.shape[0]//2]
                * torch.hann_window(win_length*2)[win_length:],
        )
        # )).unsqueeze(0)
        self.register_buffer('static_freq_minphase_wsinc', static_freq_minphase_wsinc)
        
        ## TODO: necessary?
        minphase_wsinc_w_env = 0.5 - 1/sampling_rate
        windowed_sinc = torch.sinc(
            torch.linspace(-(block_size//2*minphase_wsinc_w_env-1), block_size//2*minphase_wsinc_w_env, block_size//2)
        ) * torch.blackman_window(block_size//2)
            
        log_freq_windowed_sinc = torch.log(torch.fft.fft(
            F.pad(windowed_sinc, (block_size//4, block_size//4)),
            n = block_size,
        ) + 1e-7)
        ceps_windowed_sinc = torch.fft.ifft(torch.cat([
            log_freq_windowed_sinc[:log_freq_windowed_sinc.shape[0]//2+1],
            torch.flip(log_freq_windowed_sinc[1:log_freq_windowed_sinc.shape[0]//2], (0,))
        ]))
        ceps_windowed_sinc.imag[0] *= -1.
        ceps_windowed_sinc.real[1:ceps_windowed_sinc.shape[0]//2] *= 2.
        ceps_windowed_sinc.imag[1:ceps_windowed_sinc.shape[0]//2] *= -2.
        ceps_windowed_sinc.imag[ceps_windowed_sinc.shape[0]//2] *= -1.
        ceps_windowed_sinc[ceps_windowed_sinc.shape[0]//2+1:] = 0.
        static_freq_minphase_wsinc_env = torch.fft.rfft( F.pad(torch.fft.ifft(
            torch.exp(torch.fft.fft(ceps_windowed_sinc))
            ).real.roll(ceps_windowed_sinc.shape[0]//2-1)[:ceps_windowed_sinc.shape[0]//2],
            (0, win_length - (block_size//2))
        # ) )).unsqueeze(0)
        ) )
        
        self.register_buffer('static_freq_minphase_wsinc_env', static_freq_minphase_wsinc_env)
        

    def forward(self, units_frames, f0_frames, volume_frames,
                spk_id=None, spk_mix=None, aug_shift=None, initial_phase=None, infer=True, **kwargs):
        '''
            units_frames: B x n_frames x n_unit
            f0_frames: B x n_frames x 1
            volume_frames: B x n_frames x 1 
            spk_id: B x 1
        '''
        
        # f0 = upsample(f0_frames, self.block_size)
        # we just enough simply repeat to that because block size is short enough, it is sufficient I think.
        # print (f0_frames.shape, f0_frames.repeat(1,1,self.block_size).flatten(1).unsqueeze(-1).shape)
        f0 = f0_frames.repeat(1,1,self.block_size).flatten(1).unsqueeze(-1)
        
        # # linear interp. for low frequent f0
        # f0 = f0_frames.flatten(1)
        # # repeat a last sample
        # f0_exp = torch.cat((f0, f0[:, -1:] + (f0[:, -1:] - f0[:, -2:-1])), 1)
        # # calc slopes (differentials) sample by sample, then repeat
        # f0_slopes = (f0_exp[:, 1:] - f0_exp[:, :-1]).unsqueeze(-1).repeat(1, 1, self.block_size).flatten(1)
        # # repeat indice, this is lerp coefficients
        # # f0_repeat_idx = (torch.arange(self.block_size).to(f0)/self.block_size).unsqueeze(-1).transpose(1, 0).repeat(f0.shape)
        # f0_repeat_idx = (torch.arange(self.block_size).to(f0)).unsqueeze(-1).transpose(1, 0).repeat(f0.shape)
        # # repeat original values, then interpolate
        # f0 = f0.unsqueeze(-1).repeat(1, 1, self.block_size).flatten(1) + f0_slopes*f0_repeat_idx/self.block_size
        # f0 = f0.unsqueeze(-1)
        
        # add f0 variance
        # this expected suppress leakage of original speaker's f0 features
        # but get blurred pitch and I don't think that necessary.
        f0_variance = torch.randn_like(f0)*self.f0_input_variance
        f0 = (f0 * 2.**(-self.f0_input_variance/12.))*(2.**(f0_variance/12.))   # semitone units
        if infer:
            # TODO: maybe this is for precision, but necessary?
            x = torch.cumsum(f0.double() / self.sampling_rate, axis=1)
        else:
            x = torch.cumsum(f0 / self.sampling_rate, axis=1)
        if initial_phase is not None:
            x = x + initial_phase.to(x) / (2. * 3.141592653589793) # twopi
        x = x - torch.round(x)
        x = x.to(f0)
        
        phase_frames = 2. * 3.141592653589793 * x.reshape(x.shape[0], -1, self.block_size)[:, :, 0:1]
        
        # parameter prediction
        ctrls, hidden = self.unit2ctrl(units_frames, f0_frames, phase_frames, volume_frames,
                                       spk_id=spk_id, spk_mix=spk_mix, aug_shift=aug_shift,
                                    #    infer=infer)
        )
        
        if self.use_f0_offset:
            # apply predicted f0 offset
            # NOTE: use f0 offset can be generalize inputs and fit target more, but pitch tracking is get blurry (oscillated) and feeling softer depending on the target
            f0 = f0 + (((ctrls['f0_offset'] - 2.)*0.5)).unsqueeze(-1).repeat(1,1,1,self.f0_offset_size_downsamples).flatten(2).reshape(f0.shape[0], f0.shape[1], 1)
            
        if infer:
            x = torch.cumsum(f0.double() / self.sampling_rate, axis=1)
        else:
            x = torch.cumsum(f0 / self.sampling_rate, axis=1)
        if initial_phase is not None:
            x = x + initial_phase.to(x) / (2. * 3.141592653589793)
            
        # xh = x + 0.5    
        # xh = x + pwm
        # xh = x + f0/self.sampling_rate 
        
        x = x - torch.round(x)
        x = x.to(f0)
        # xh = xh - torch.round(xh)
        # xh = xh.to(f0)
        
        
        # exciter phase
        
        # filters
        src_filter = torch.exp(ctrls['harmonic_magnitude'] + 1.j * ctrls['harmonic_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        src_filter = torch.cat((src_filter, src_filter[:,-1:,:]), 1).permute(0, 2, 1)
        
        if self.use_noise:
            noise_filter = torch.exp(ctrls['noise_magnitude'] + 1.j * ctrls['noise_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
            noise_filter = torch.cat((noise_filter, noise_filter[:,-1:,:]), 1).permute(0, 2, 1)

        if self.add_noise:
            add_noise_filter = torch.exp(ctrls['add_noise_magnitude'] + 3.141592653589793j * ctrls['add_noise_phase'])/self.block_size
            add_noise_filter = torch.cat((add_noise_filter, add_noise_filter[:,-1:,:]), 1).permute(0, 2, 1)
            
        if self.use_short_filter:
            src_short_filter = torch.exp(ctrls['short_harmonic_magnitude'] + 1.j * ctrls['short_harmonic_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
            src_short_filter = torch.cat((src_short_filter, src_short_filter[:,-1:,:]), 1).permute(0, 2, 1)
            
        if self.use_noise and self.use_noise_short_filter:
            noise_short_filter = torch.exp(ctrls['short_noise_magnitude'] + 1.j * ctrls['short_noise_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
            noise_short_filter = torch.cat((noise_short_filter, noise_short_filter[:,-1:,:]), 1).permute(0, 2, 1)
        
        
        # Dirac delta
        # note that its not accurate at boundary but fast and almost enough
        combtooth = torch.where(x.roll(-1) - x < 0., 1., 0.)
        combtooth = combtooth.squeeze(-1)
        
                
        if self.use_harmonic_env:
            harmonic_env_flat = torch.clamp(ctrls['harmonic_envelope_magnitude'], min=-1., max=1.).flatten(1)   # clamps to prevent exploding gradients...?
            
            harmonic_env = harmonic_env_flat.unsqueeze(-1).repeat(1, 1, self.harmonic_env_size_downsamples).flatten(1)
            
            # apply it to source
            combtooth *= harmonic_env

        pad_mode = 'constant'
        
        if self.use_short_filter:
            combtooth_stft_s = torch.stft(
                                combtooth,
                                n_fft = self.win_length,
                                win_length = self.win_length,
                                hop_length = self.win_length//4//4,
                                window = self.window,
                                center = True,
                                return_complex = True,
                                pad_mode = pad_mode)
            
            combtooth_stft_s = combtooth_stft_s * self.static_freq_minphase_wsinc.unsqueeze(-1).repeat(1, combtooth.shape[1]//(self.win_length//4//4) + 1)
            combtooth_stft_s = combtooth_stft_s * src_short_filter
        
        if self.use_noise:
            # noise exciter
            noise_t = self.static_noise_t.unsqueeze(0).repeat(combtooth.shape[0], combtooth.shape[1]//self.static_noise_t.shape[0] + 1)[:, :combtooth.shape[1]]
            
            if self.use_noise_env:
                noise_env_flat = (torch.clamp(ctrls['noise_envelope_magnitude'], min=-1., max=1.)).flatten(1)
                
                # repeat and fit shape
                noise_env = noise_env_flat.unsqueeze(-1).repeat(1, 1, self.noise_env_size_downsamples).flatten(1)
                
                noise_t = noise_t * noise_env
            
            if self.use_noise_short_filter:
                noise_stft_s = torch.stft(
                                    noise_t,
                                    n_fft = self.win_length,
                                    win_length = self.win_length,
                                    hop_length = self.win_length//4//4,
                                    window = self.window,
                                    center = True,
                                    return_complex = True,
                                    pad_mode = pad_mode)
                
                noise_stft_s = noise_stft_s * noise_short_filter
                            
        combtooth_stft = torch.stft(
                            combtooth,
                            n_fft = self.win_length,
                            win_length = self.win_length,
                            hop_length = self.block_size//4,
                            window = self.window,
                            center = True,
                            return_complex = True,
                            pad_mode = pad_mode) * src_filter * self.static_freq_minphase_wsinc.unsqueeze(-1).repeat(1, combtooth.shape[1]//(self.block_size//4) + 1)
        
        if self.use_noise:
            noise_stft = torch.stft(
                noise_t,
                n_fft = self.win_length,
                win_length = self.win_length,
                hop_length = self.block_size//4,
                window = self.window,
                center = True,
                return_complex = True,
                pad_mode = pad_mode) * noise_filter
                # pad_mode = pad_mode) * noise_filter * self.static_freq_minphase_wsinc.unsqueeze(-1).repeat(1, combtooth.shape[1]//self.block_size + 1)
        
        if self.use_noise:
            signal_stft = combtooth_stft + noise_stft
        else:
            signal_stft = combtooth_stft
        
        # take the istft to resynthesize audio.
        signal = torch.istft(
            signal_stft,
            n_fft = self.win_length,
            win_length = self.win_length,
            hop_length = self.block_size//4,
            window = self.window,
            center = True)
        
        return signal
    
    
class CombSubMinimumNoisedPhase_export(torch.nn.Module):
    def __init__(self, 
            sampling_rate,
            block_size,
            win_length,
            n_unit=256,
            n_hidden_channels=256,
            n_spk=1,
            use_speaker_embed=True,
            use_embed_conv=True,
            spk_embed_channels=256,
            f0_input_variance=0.1,
            f0_offset_size_downsamples=1,
            noise_env_size_downsamples=4,
            harmonic_env_size_downsamples=4,
            use_harmonic_env=False,
            use_noise_env=True,
            use_add_noise_env=True,
            noise_to_harmonic_phase=False,
            add_noise=False,
            use_phase_offset=False,
            use_f0_offset=False,
            no_use_noise=False,
            use_short_filter=False,
            use_noise_short_filter=False,
            use_pitch_aug=False,
            noise_seed=289,
            onnx_unit2ctrl=None,
            export_onnx=False,
            device='cpu'):
        super().__init__()

        print(' [DDSP Model] Minimum-Phase harmonic Source Combtooth Subtractive Synthesiser')
        
        # device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # params
        self.register_buffer("sampling_rate", torch.tensor(sampling_rate))
        
        # should be constant for onnx
        self.block_size = block_size
        self.win_length = win_length
        self.f0_offset_size_downsamples = f0_offset_size_downsamples
        self.noise_env_size_downsamples = noise_env_size_downsamples
        self.harmonic_env_size_downsamples = harmonic_env_size_downsamples
        
        self.register_buffer("window", torch.hann_window(win_length))
        self.register_buffer("f0_input_variance", torch.tensor(f0_input_variance))
        self.register_buffer("use_harmonic_env", torch.tensor(use_harmonic_env))
        self.register_buffer("use_noise_env", torch.tensor(use_noise_env))
        self.register_buffer("use_add_noise_env", torch.tensor(use_add_noise_env))
        self.register_buffer("noise_to_harmonic_phase", torch.tensor(noise_to_harmonic_phase))
        self.register_buffer("use_f0_offset", torch.tensor(use_f0_offset))
        self.register_buffer("use_speaker_embed", torch.tensor(use_speaker_embed))
        self.register_buffer("use_embed_conv", torch.tensor(use_embed_conv))
        self.register_buffer("noise_seed", torch.tensor(noise_seed))
        
        self.pred_filter_size = win_length // 2 + 1
        
        self.use_noise = not no_use_noise
        
        
        #Unit2Control
        split_map = {
        }
        if self.use_noise:
            if use_noise_env:
                split_map['noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        if use_harmonic_env:
            split_map['harmonic_envelope_magnitude'] = block_size//harmonic_env_size_downsamples
        if use_f0_offset:
            split_map['f0_offset'] = block_size//f0_offset_size_downsamples
        if add_noise:
            split_map['add_noise_magnitude'] = self.pred_filter_size
            split_map['add_noise_phase'] = self.pred_filter_size
            if use_add_noise_env:
                split_map['add_noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        if use_phase_offset:
            split_map['phase_offset'] = self.pred_filter_size
        if use_short_filter:
            # split_map['short_harmonic_magnitude'] = (512//4)*(16//2 + 1)
            # split_map['short_harmonic_phase'] = (512//4)*(16//2 + 1)
            split_map['short_harmonic_magnitude'] = self.pred_filter_size * 4
            split_map['short_harmonic_phase'] = self.pred_filter_size * 4
        if self.use_noise:
            if use_noise_short_filter:
                split_map['short_noise_magnitude'] = self.pred_filter_size * 4
                split_map['short_noise_phase'] = self.pred_filter_size * 4
                
        split_map['harmonic_magnitude'] = self.pred_filter_size * 4
        split_map['harmonic_phase'] = self.pred_filter_size * 4
        split_map['noise_magnitude'] = self.pred_filter_size * 4
        split_map['noise_phase'] = self.pred_filter_size * 4
            
        self.use_short_filter = use_short_filter
        self.use_noise_short_filter = use_noise_short_filter
            
        
        if onnx_unit2ctrl is not None:
            from .unit2control import Unit2ControlGE2E_onnx
            self.unit2ctrl = Unit2ControlGE2E_onnx(onnx_unit2ctrl, split_map)
        elif export_onnx:
            from .unit2control import Unit2ControlGE2E_export
            self.unit2ctrl = Unit2ControlGE2E_export(n_unit, spk_embed_channels, split_map,
                                            n_hidden_channels=n_hidden_channels,
                                            n_spk=n_spk,
                                            use_pitch_aug=use_pitch_aug,
                                            use_spk_embed=use_speaker_embed,
                                            use_embed_conv=use_embed_conv,
                                            embed_conv_channels=64, conv_stack_middle_size=32)
        else:
            from .unit2control import Unit2ControlGE2E
            self.unit2ctrl = Unit2ControlGE2E(n_unit, spk_embed_channels, split_map,
                                            n_hidden_channels=n_hidden_channels,
                                            n_spk=n_spk,
                                            use_pitch_aug=use_pitch_aug,
                                            use_spk_embed=use_speaker_embed,
                                            use_embed_conv=use_embed_conv,
                                            embed_conv_channels=64, conv_stack_middle_size=32)
        
        # generate static noise
        self.gen = torch.Generator()
        self.gen.manual_seed(noise_seed)
        static_noise_t = (torch.rand([
            win_length*127  # about 5.9sec when sampling_rate=44100 and win_length=2048
        ], generator=self.gen)*2.0-1.0)
        self.register_buffer('static_noise_t', static_noise_t)
        
        # generate minimum-phase windowed sinc signal for harmonic source
        ## TODO: functional
        minphase_wsinc_w = 0.5 - 1/sampling_rate
        phase = torch.linspace(-(win_length*minphase_wsinc_w-1), win_length*minphase_wsinc_w, win_length)
        windowed_sinc = torch.sinc(
                phase
        ) * torch.blackman_window(win_length)
        log_freq_windowed_sinc = torch.log(torch.fft.fft(
            F.pad(windowed_sinc, (win_length//2, win_length//2)),
            n = win_length*2,
        ) + 1e-7)
        ceps_windowed_sinc = torch.fft.ifft(torch.cat([
            log_freq_windowed_sinc[:log_freq_windowed_sinc.shape[0]//2+1],
            torch.flip(log_freq_windowed_sinc[1:log_freq_windowed_sinc.shape[0]//2], (0,))
        ]))
        ceps_windowed_sinc.imag[0] *= -1.
        ceps_windowed_sinc.real[1:ceps_windowed_sinc.shape[0]//2] *= 2.
        ceps_windowed_sinc.imag[1:ceps_windowed_sinc.shape[0]//2] *= -2.
        ceps_windowed_sinc.imag[ceps_windowed_sinc.shape[0]//2] *= -1.
        ceps_windowed_sinc[ceps_windowed_sinc.shape[0]//2+1:] = 0.
        
        static_freq_minphase_wsinc = torch.view_as_real(torch.fft.rfft( torch.fft.ifft(
        # static_freq_minphase_wsinc = torch.fft.rfft( torch.fft.ifft(
            torch.exp(torch.fft.fft(ceps_windowed_sinc))
            ).real.roll(ceps_windowed_sinc.shape[0]//2-1)[:ceps_windowed_sinc.shape[0]//2]
                * torch.hann_window(win_length*2)[win_length:],
        # )
        )).unsqueeze(0)
        self.register_buffer('static_freq_minphase_wsinc', static_freq_minphase_wsinc)
        # self.static_freq_minphase_wsinc = static_freq_minphase_wsinc.to(device)
        
        ## TODO: necessary?
        minphase_wsinc_w_env = 0.5 - 1/sampling_rate
        windowed_sinc = torch.sinc(
            # torch.linspace(-(block_size//2-1)*minphase_wsinc_w_env, block_size//2*minphase_wsinc_w_env, block_size//2)
            torch.linspace(-(block_size//2*minphase_wsinc_w_env-1), block_size//2*minphase_wsinc_w_env, block_size//2)
        ) * torch.blackman_window(block_size//2)
            
        log_freq_windowed_sinc = torch.log(torch.fft.fft(
            F.pad(windowed_sinc, (block_size//4, block_size//4)),
            n = block_size,
        ) + 1e-7)
        ceps_windowed_sinc = torch.fft.ifft(torch.cat([
            log_freq_windowed_sinc[:log_freq_windowed_sinc.shape[0]//2+1],
            torch.flip(log_freq_windowed_sinc[1:log_freq_windowed_sinc.shape[0]//2], (0,))
        ]))
        ceps_windowed_sinc.imag[0] *= -1.
        ceps_windowed_sinc.real[1:ceps_windowed_sinc.shape[0]//2] *= 2.
        ceps_windowed_sinc.imag[1:ceps_windowed_sinc.shape[0]//2] *= -2.
        ceps_windowed_sinc.imag[ceps_windowed_sinc.shape[0]//2] *= -1.
        ceps_windowed_sinc[ceps_windowed_sinc.shape[0]//2+1:] = 0.
        static_freq_minphase_wsinc_env = torch.view_as_real(torch.fft.rfft( F.pad(torch.fft.ifft(
        # static_freq_minphase_wsinc_env = torch.fft.rfft( F.pad(torch.fft.ifft(
            torch.exp(torch.fft.fft(ceps_windowed_sinc))
            ).real.roll(ceps_windowed_sinc.shape[0]//2-1)[:ceps_windowed_sinc.shape[0]//2],
            (0, win_length - (block_size//2))
        ) )).unsqueeze(0)
        # ) )
        
        self.register_buffer('static_freq_minphase_wsinc_env', static_freq_minphase_wsinc_env)
        # self.static_freq_minphase_wsinc_env = static_freq_minphase_wsinc_env.to(device)
        
        # stft
        self.stft = STFT(
            filter_length=self.win_length,
            hop_length=self.block_size,
            win_length=self.win_length,
            window=torch.hann_window,
        )
        
        self.cmul = lambda ar, ai, br, bi: \
            (ar*br - ai*bi, ar*bi + ai*br,)
        

    def forward(self, units_frames, f0_frames, volume_frames,
                spk_id=None, spk_mix=None):
        '''
            units_frames: B x n_frames x n_unit
            f0_frames: B x n_frames x 1
            volume_frames: B x n_frames x 1 
            spk_id: B x 1
        '''
        
        # we just enough simply repeat to that because block size is short enough, it is sufficient I think.
        # print (f0_frames.shape, f0_frames.repeat(1,1,self.block_size).flatten(1).unsqueeze(-1).shape)
        f0 = f0_frames.repeat(1,1,self.block_size).flatten(1).unsqueeze(-1)
        
        # # linear interp. for low frequent f0
        # f0 = f0_frames.flatten(1)
        # # repeat a last sample
        # f0_exp = torch.cat((f0, f0[:, -1:] + (f0[:, -1:] - f0[:, -2:-1])), 1)
        # # calc slopes (differentials) sample by sample, then repeat
        # f0_slopes = (f0_exp[:, 1:] - f0_exp[:, :-1]).unsqueeze(-1).repeat(1, 1, self.block_size).flatten(1)
        # # repeat indice, this is lerp coefficients
        # f0_repeat_idx = (torch.arange(self.block_size).to(f0)/self.block_size).unsqueeze(-1).transpose(1, 0).repeat(f0.shape)
        # # f0_repeat_idx = (torch.arange(self.block_size).to(f0)).unsqueeze(-1).transpose(1, 0).repeat(f0.shape)
        # # repeat original values, then interpolate
        # f0 = f0.unsqueeze(-1).repeat(1, 1, self.block_size).flatten(1) + f0_slopes*f0_repeat_idx/self.block_size
        # f0 = f0.unsqueeze(-1)
        
        # # add f0 variance: currently unused
        # # this expected suppress leakage of original speaker's f0 features
        # # but get blurred pitch and I don't think that necessary.
        # f0_variance = torch.randn_like(f0)*self.f0_input_variance
        # f0 = (f0 * 2.**(-self.f0_input_variance/12.))*(2.**(f0_variance/12.))   # semitone units
        
        x = torch.cumsum(f0.double() / self.sampling_rate, axis=1)
        
        # if initial_phase is not None:
        #     x = x + initial_phase.to(x) / (2. * 3.141592653589793) # twopi
        x = x - torch.round(x)
        x = x.to(f0)
        
        phase_frames = 2. * 3.141592653589793 * x.reshape(x.shape[0], -1, self.block_size)[:, :, 0:1]
        
        # parameter prediction
        ctrls, hidden = self.unit2ctrl(units_frames, f0_frames, phase_frames, volume_frames,
                                    #    spk_id=spk_id, spk_mix=spk_mix, aug_shift=aug_shift,
                                    spk_id=spk_id, spk_mix=spk_mix,
                                    #    infer=infer)
        )
        
        # # apply predicted f0 offset: currently unused
        # # NOTE: use f0 offset can be generalize inputs and fit target more, but pitch tracking is get blurry (oscillated) and feeling softer depending on the target
        # f0 = f0 + (((ctrls['f0_offset'] - 2.)*0.5)).unsqueeze(-1).repeat(1,1,1,self.f0_offset_size_downsamples).flatten(2).reshape(f0.shape[0], f0.shape[1], 1)
            
        x = torch.cumsum(f0.double() / self.sampling_rate, axis=1)
        
        # if initial_phase is not None:
        #     x = x + initial_phase.to(x) / (2. * 3.141592653589793)
        # xh = x + 0.5
        
        x = x - torch.round(x)
        x = x.to(f0)
        
        # xh = xh - torch.round(xh)
        # xh = xh.to(f0)
        
        
        # exciter phase
        
        # filters
        # src_filter = torch.exp(ctrls['harmonic_magnitude'] + 1.j * ctrls['harmonic_phase'])
        # src_filter = torch.cat((src_filter, src_filter[:,-1:,:]), 1).permute(0, 2, 1)
        src_filter = torch.exp(ctrls['harmonic_magnitude']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        src_filter_i = src_filter * torch.sin(ctrls['harmonic_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        src_filter = src_filter * torch.cos(ctrls['harmonic_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        # src_filter = torch.stack((src_filter, src_filter_i), -1)
        # src_filter = torch.cat((src_filter, src_filter[:,-1:,:,:]), 1).permute(0, 2, 1, 3)
        src_filter = torch.cat((src_filter, src_filter[:,-1:,:]), 1).permute(0, 2, 1)
        src_filter_i = torch.cat((src_filter_i, src_filter_i[:,-1:,:]), 1).permute(0, 2, 1)
        
        # noise_filter = torch.exp(ctrls['noise_magnitude'] + 1.j * ctrls['noise_phase'])
        # noise_filter = torch.cat((noise_filter, noise_filter[:,-1:,:]), 1).permute(0, 2, 1)        
        noise_filter = torch.exp(ctrls['noise_magnitude']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        noise_filter_i = noise_filter * torch.sin(ctrls['noise_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        noise_filter = noise_filter * torch.cos(ctrls['noise_phase']).reshape(x.shape[0], -1, self.win_length//2 + 1)
        # noise_filter = torch.stack((noise_filter, noise_filter_i), -1)
        # noise_filter = torch.cat((noise_filter, noise_filter[:,-1:,:,:]), 1).permute(0, 2, 1, 3)
        noise_filter = torch.cat((noise_filter, noise_filter[:,-1:,:]), 1).permute(0, 2, 1)
        noise_filter_i = torch.cat((noise_filter_i, noise_filter_i[:,-1:,:]), 1).permute(0, 2, 1)
        
        # Dirac delta
        # note that its not accurate at boundary but fast and almost enough
        combtooth = torch.where(x.roll(-1) - x < 0., 1., 0.)
        combtooth = combtooth.squeeze(-1)
        
        # combtooth = torch.where(x+0.5 < f0.double() / self.sampling_rate, 1., 0.)
        # combtooth = combtooth.squeeze(-1)
        
        if self.use_harmonic_env:
            harmonic_env_flat = torch.clamp(ctrls['harmonic_envelope_magnitude'], min=-1., max=1.).flatten(1)   # clamps to prevent exploding gradients...?
            
            harmonic_env = harmonic_env_flat.unsqueeze(-1).repeat(1, 1, self.harmonic_env_size_downsamples).flatten(1)
            
            # apply it to source
            combtooth *= harmonic_env
        
        # # lazy, not accurate, but fast linear interpolation
        # # repeat a last sample
        # harmonic_env_exp = torch.cat((harmonic_env_flat, harmonic_env_flat[:, -1:]), 1)
        # # calc slopes (differentials) sample by sample, then repeat
        # harmonic_env_slopes = (harmonic_env_exp[:, 1:] - harmonic_env_exp[:, :-1]).unsqueeze(-1).repeat(1, 1, self.harmonic_env_size_downsamples).flatten(1)
        # # repeat indice, this is lerp coefficients
        # # harmonic_env_repeat_idx = (torch.arange(self.harmonic_env_size_downsamples).to(harmonic_env_flat)/self.harmonic_env_size_downsamples).unsqueeze(-1).transpose(1, 0).repeat(harmonic_env_flat.shape)
        # harmonic_env_repeat_idx = (torch.arange(self.harmonic_env_size_downsamples).to(harmonic_env_flat)).unsqueeze(-1).transpose(1, 0).repeat(harmonic_env_flat.shape)
        # # repeat original values, then interpolate
        # harmonic_env = harmonic_env_flat.unsqueeze(-1).repeat(1, 1, self.harmonic_env_size_downsamples).flatten(1) + harmonic_env_slopes*harmonic_env_repeat_idx/self.harmonic_env_size_downsamples
        
        # # # apply it to source
        # combtooth *= harmonic_env

        pad_mode = 'constant'
        
        # noise exciter
        if self.use_noise:
            noise_t = self.static_noise_t.unsqueeze(0).repeat(combtooth.shape[0], combtooth.shape[1]//self.static_noise_t.shape[0] + 1)[:, :combtooth.shape[1]]
            
            if self.use_noise_env:
                noise_env_flat = (torch.clamp(ctrls['noise_envelope_magnitude'], min=-1., max=1.)).flatten(1)
                
                # repeat and fit shape
                noise_env = noise_env_flat.unsqueeze(-1).repeat(1, 1, self.noise_env_size_downsamples).flatten(1)
        
                # noise_env_flat = (F.relu(ctrls['noise_envelope_magnitude'])).flatten(1)
                # noise_env_exp = torch.cat((noise_env_flat, noise_env_flat[:, -1:]), 1)
                # noise_env_slopes = (noise_env_exp[:, 1:] - noise_env_exp[:, :-1]).unsqueeze(-1).repeat(1, 1, self.noise_env_size_downsamples).flatten(1)
                # noise_env_repeat_idx = (torch.arange(self.noise_env_size_downsamples).to(noise_env_flat)).unsqueeze(-1).transpose(1, 0).repeat(noise_env_flat.shape)
                # noise_env = noise_env_flat.unsqueeze(-1).repeat(1, 1, self.noise_env_size_downsamples).flatten(1) + noise_env_slopes*noise_env_repeat_idx/self.noise_env_size_downsamples
                noise_t = noise_t * noise_env
        
        combtooth_stft, combtooth_stft_i = self.stft.transform(
            combtooth,
            pad_mode = pad_mode)
        
        mp_filter = self.static_freq_minphase_wsinc.unsqueeze(-2).repeat(combtooth.shape[0], 1, combtooth.shape[1]//self.block_size + 1, 1)
        combtooth_stft, combtooth_stft_i = self.cmul(
            combtooth_stft, combtooth_stft_i,
            mp_filter[:, :, :, 0], mp_filter[:, :, :, 1])
        
        combtooth_stft, combtooth_stft_i = self.cmul(
            combtooth_stft, combtooth_stft_i,
            src_filter, src_filter_i)
        
        noise_stft, noise_stft_i = self.stft.transform(
            noise_t,
            pad_mode = pad_mode)
        
        noise_stft, noise_stft_i = self.cmul(
            noise_stft, noise_stft_i,
            noise_filter, noise_filter_i)
        
        # take the istft to resynthesize audio.
        signal = self.stft.inverse(
            noise_stft,
            noise_stft_i).squeeze(1)
        
        
        return signal
    
    
class NMPSFHiFi(torch.nn.Module):
    def __init__(self, 
            sampling_rate,
            block_size,
            win_length,
            n_unit=256,
            n_hidden_channels=256,
            n_spk=1,
            use_speaker_embed=True,
            use_embed_conv=True,
            spk_embed_channels=256,
            f0_input_variance=0.1,
            f0_offset_size_downsamples=1,
            noise_env_size_downsamples=4,
            harmonic_env_size_downsamples=4,
            use_harmonic_env=False,
            use_noise_env=True,
            use_add_noise_env=True,
            noise_to_harmonic_phase=False,
            add_noise=False,
            use_phase_offset=False,
            use_f0_offset=False,
            use_short_filter=False,
            use_noise_short_filter=False,
            use_pitch_aug=False,
            nsf_hifigan_in=128,
            nsf_hifigan_h=None,
            noise_seed=289,
            onnx_unit2ctrl=None,
            export_onnx=False,
            device=None):
        super().__init__()

        print(' [Model] NSF-HiFiGAN Synthesiser')
        
        # device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # params
        self.register_buffer("sampling_rate", torch.tensor(sampling_rate))
        self.register_buffer("block_size", torch.tensor(block_size))
        self.register_buffer("win_length", torch.tensor(win_length))
        self.register_buffer("window", torch.hann_window(win_length))
        self.register_buffer("f0_input_variance", torch.tensor(f0_input_variance))
        self.register_buffer("f0_offset_size_downsamples", torch.tensor(f0_offset_size_downsamples))
        self.register_buffer("noise_env_size_downsamples", torch.tensor(noise_env_size_downsamples))
        self.register_buffer("harmonic_env_size_downsamples", torch.tensor(harmonic_env_size_downsamples))
        self.register_buffer("use_harmonic_env", torch.tensor(use_harmonic_env))
        self.register_buffer("use_noise_env", torch.tensor(use_noise_env))
        self.register_buffer("use_add_noise_env", torch.tensor(use_add_noise_env))
        self.register_buffer("noise_to_harmonic_phase", torch.tensor(noise_to_harmonic_phase))
        # self.register_buffer("add_noise", torch.tensor(add_noise))
        self.register_buffer("use_f0_offset", torch.tensor(use_f0_offset))
        self.register_buffer("use_speaker_embed", torch.tensor(use_speaker_embed))
        self.register_buffer("use_embed_conv", torch.tensor(use_embed_conv))
        self.register_buffer("noise_seed", torch.tensor(noise_seed))
        
        if use_short_filter or use_noise_short_filter:
            self.register_buffer("window_s", torch.hann_window(16))
        
        if add_noise is None:
            self.add_noise = add_noise
        else:
            self.register_buffer("add_noise", torch.tensor(add_noise))
        
        if use_phase_offset is None:
            self.use_phase_offset = use_phase_offset
        else:
            self.register_buffer("use_phase_offset", torch.tensor(use_phase_offset))

        self.pred_filter_size = win_length // 2 + 1
        
        
        #Unit2Control
        split_map = {
            'harmonic_magnitude': self.pred_filter_size,
            'harmonic_phase': self.pred_filter_size,
            # 'noise_magnitude': self.pred_filter_size,
            # 'noise_phase': self.pred_filter_size,
            'nsf_param': nsf_hifigan_in,
        }
        # if use_noise_env:
        #     split_map['noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        # if use_harmonic_env:
        #     split_map['harmonic_envelope_magnitude'] = block_size//harmonic_env_size_downsamples
        if use_f0_offset:
            split_map['f0_offset'] = block_size//f0_offset_size_downsamples
        # if add_noise:
        #     split_map['add_noise_magnitude'] = self.pred_filter_size
        #     split_map['add_noise_phase'] = self.pred_filter_size
        #     if use_add_noise_env:
        #         split_map['add_noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        # if use_phase_offset:
        #     split_map['phase_offset'] = self.pred_filter_size
        # if use_short_filter:
        #     split_map['short_harmonic_magnitude'] = block_size
        #     split_map['short_harmonic_phase'] = block_size
        # if use_noise_short_filter:
        #     split_map['short_noise_magnitude'] = block_size
        #     split_map['short_noise_phase'] = block_size
        if use_noise_env:
            split_map['noise_envelope_magnitude'] = block_size//noise_env_size_downsamples
        if use_harmonic_env:
            split_map['harmonic_envelope_magnitude'] = block_size//harmonic_env_size_downsamples
        # if use_harmonic_env:
        #     split_map['harmonic_envelope_magnitude'] = block_size//harmonic_env_size_downsamples
            
        self.use_short_filter = use_short_filter
        self.use_noise_short_filter = use_noise_short_filter
            
        
        if onnx_unit2ctrl is not None:
            from .unit2control import Unit2ControlGE2E_onnx
            self.unit2ctrl = Unit2ControlGE2E_onnx(onnx_unit2ctrl, split_map)
        elif export_onnx:
            from .unit2control import Unit2ControlGE2E_export
            self.unit2ctrl = Unit2ControlGE2E_export(n_unit, spk_embed_channels, split_map,
                                            n_hidden_channels=n_hidden_channels,
                                            n_spk=n_spk,
                                            use_pitch_aug=use_pitch_aug,
                                            use_spk_embed=use_speaker_embed,
                                            use_embed_conv=use_embed_conv,
                                            embed_conv_channels=64, conv_stack_middle_size=32)
        else:
            from .unit2control import Unit2ControlGE2E
            self.unit2ctrl = Unit2ControlGE2E(n_unit, spk_embed_channels, split_map,
                                            n_hidden_channels=n_hidden_channels,
                                            n_spk=n_spk,
                                            use_pitch_aug=use_pitch_aug,
                                            use_spk_embed=use_speaker_embed,
                                            use_embed_conv=use_embed_conv,
                                            embed_conv_channels=64, conv_stack_middle_size=32)
            
        from .nsf_hifigan.models import GeneratorDirectSource
        self.generator = GeneratorDirectSource(nsf_hifigan_h)
        
        # generate static noise
        self.gen = torch.Generator()
        self.gen.manual_seed(noise_seed)
        static_noise_t = (torch.rand([
            win_length*127  # about 5.9sec when sampling_rate=44100 and win_length=2048
        ], generator=self.gen)*2.0-1.0)
        # if self.noise_to_harmonic_phase:
        #     dump = torch.zeros_like(static_noise_t)
        #     dump_samples = int(sampling_rate / 300.0)    # samples of 300Hz
        #     dump[:dump_samples] = torch.linspace(1.0, 0.0, dump_samples) ** 2.
        #     static_noise_t *= dump
        self.register_buffer('static_noise_t', static_noise_t)

        if add_noise:
            static_add_noise_t = (torch.rand([
            win_length*127  # about 5.9sec when sampling_rate=44100 and win_length=2048
            ], generator=self.gen)*2.0-1.0)
            self.register_buffer('static_add_noise_t', static_add_noise_t)
        
        # generate minimum-phase windowed sinc signal for harmonic source
        ## TODO: functional
        minphase_wsinc_w = 0.5
        # minphase_wsinc_w = 16 / win_length
        # minphase_wsinc_w = 1. / 16.
        # minphase_wsinc_w = 0.25
        phase = torch.linspace(-(win_length-1)*minphase_wsinc_w, win_length*minphase_wsinc_w, win_length)
        windowed_sinc = torch.sinc(
                phase
        ) * torch.blackman_window(win_length)
        log_freq_windowed_sinc = torch.log(torch.fft.fft(
            F.pad(windowed_sinc, (win_length//2, win_length//2)),
            n = win_length*2,
        ) + 1e-7)
        ceps_windowed_sinc = torch.fft.ifft(torch.cat([
            log_freq_windowed_sinc[:log_freq_windowed_sinc.shape[0]//2+1],
            torch.flip(log_freq_windowed_sinc[1:log_freq_windowed_sinc.shape[0]//2], (0,))
        ]))
        ceps_windowed_sinc.imag[0] *= -1.
        ceps_windowed_sinc.real[1:ceps_windowed_sinc.shape[0]//2] *= 2.
        ceps_windowed_sinc.imag[1:ceps_windowed_sinc.shape[0]//2] *= -2.
        ceps_windowed_sinc.imag[ceps_windowed_sinc.shape[0]//2] *= -1.
        ceps_windowed_sinc[ceps_windowed_sinc.shape[0]//2+1:] = 0.
        
        static_freq_minphase_wsinc = torch.fft.rfft( torch.fft.ifft(
            torch.exp(torch.fft.fft(ceps_windowed_sinc))
            ).real.roll(ceps_windowed_sinc.shape[0]//2-1)[:ceps_windowed_sinc.shape[0]//2]
                * torch.hann_window(win_length*2)[win_length:],
        )
        self.register_buffer('static_freq_minphase_wsinc', static_freq_minphase_wsinc)
        
        ## TODO: necessary?
        minphase_wsinc_w_env = 0.5
        windowed_sinc = torch.sinc(
            torch.linspace(-(block_size//2-1)*minphase_wsinc_w_env, block_size//2*minphase_wsinc_w_env, block_size//2)
        ) * torch.blackman_window(block_size//2)
            
        log_freq_windowed_sinc = torch.log(torch.fft.fft(
            F.pad(windowed_sinc, (block_size//4, block_size//4)),
            n = block_size,
        ) + 1e-7)
        ceps_windowed_sinc = torch.fft.ifft(torch.cat([
            log_freq_windowed_sinc[:log_freq_windowed_sinc.shape[0]//2+1],
            torch.flip(log_freq_windowed_sinc[1:log_freq_windowed_sinc.shape[0]//2], (0,))
        ]))
        ceps_windowed_sinc.imag[0] *= -1.
        ceps_windowed_sinc.real[1:ceps_windowed_sinc.shape[0]//2] *= 2.
        ceps_windowed_sinc.imag[1:ceps_windowed_sinc.shape[0]//2] *= -2.
        ceps_windowed_sinc.imag[ceps_windowed_sinc.shape[0]//2] *= -1.
        ceps_windowed_sinc[ceps_windowed_sinc.shape[0]//2+1:] = 0.
        static_freq_minphase_wsinc_env = torch.fft.rfft( F.pad(torch.fft.ifft(
            torch.exp(torch.fft.fft(ceps_windowed_sinc))
            ).real.roll(ceps_windowed_sinc.shape[0]//2-1)[:ceps_windowed_sinc.shape[0]//2],
            (0, win_length - (block_size//2))
        ) )
        
        self.register_buffer('static_freq_minphase_wsinc_env', static_freq_minphase_wsinc_env)
        

    def forward(self, units_frames, f0_frames, volume_frames,
                spk_id=None, spk_mix=None, aug_shift=None, initial_phase=None, infer=True, **kwargs):
        '''
            units_frames: B x n_frames x n_unit
            f0_frames: B x n_frames x 1
            volume_frames: B x n_frames x 1 
            spk_id: B x 1
        '''
        
        # f0 = upsample(f0_frames, self.block_size)
        # we just enough simply repeat to that because block size is short enough, it is sufficient I think.
        # print (f0_frames.shape, f0_frames.repeat(1,1,self.block_size).flatten(1).unsqueeze(-1).shape)
        f0 = f0_frames.repeat(1,1,self.block_size).flatten(1).unsqueeze(-1)
        # add f0 variance
        # this expected suppress leakage of original speaker's f0 features
        # but get blurred pitch and I don't think that necessary.
        f0_variance = torch.rand_like(f0)*self.f0_input_variance
        f0 = (f0 * 2.**(-self.f0_input_variance/12.))*(2.**(f0_variance/12.))   # semitone units
        if infer:
            # TODO: maybe this is for precision, but necessary?
            x = torch.cumsum(f0.double() / self.sampling_rate, axis=1)
        else:
            x = torch.cumsum(f0 / self.sampling_rate, axis=1)
        if initial_phase is not None:
            x = x + initial_phase.to(x) / (2. * 3.141592653589793) # twopi
        # x = x - torch.round(x)
        # x = x.to(f0)
        x = x - torch.floor(x)
        x = x.to(f0)
        
        # phase_frames = 2. * torch.pi * x[:, ::self.block_size, :]
        # phase_frames = torch.tensor([2. * 3.141592653589793])[None, None, :].repeat(x.shape[0], x.shape[1]//self.block_size, self.block_size) * x.reshape(x.shape[0], -1, self.block_size)[:, :, 0:1]
        phase_frames = 2. * 3.141592653589793 * x.reshape(x.shape[0], -1, self.block_size)[:, :, 0:1]
        
        # parameter prediction
        ctrls, hidden = self.unit2ctrl(units_frames, f0_frames, phase_frames, volume_frames,
                                       spk_id=spk_id, spk_mix=spk_mix, aug_shift=aug_shift)
        
        if self.use_f0_offset:
            # apply predicted f0 offset
            # NOTE: use f0 offset can be generalize inputs and fit target more, but pitch tracking is get blurry (oscillated) and feeling softer depending on the target
            f0 = f0 + (((ctrls['f0_offset'] - 2.)*0.5)).unsqueeze(-1).repeat(1,1,1,self.f0_offset_size_downsamples).flatten(2).reshape(f0.shape[0], f0.shape[1], 1)
            # print(f0.shape)
            
            if infer:
                x = torch.cumsum(f0.double() / self.sampling_rate, axis=1)
            else:
                x = torch.cumsum(f0 / self.sampling_rate, axis=1)
            if initial_phase is not None:
                x = x + initial_phase.to(x) / (2. * 3.141592653589793)
            # x = x - torch.round(x)
            # x = x.to(f0)
            x = x - torch.floor(x)
            x = x.to(f0)
            
        # print(hidden.shape, f0.reshape(f0.shape[0], -1, self.block_size)[:, :, 0:1].shape)
        
        # filters
        src_filter = torch.exp(ctrls['harmonic_magnitude'] + 3.141592653589793j * ctrls['harmonic_phase'])
        src_filter = torch.cat((src_filter, src_filter[:,-1:,:]), 1).permute(0, 2, 1)
        
        # noise_filter = torch.exp(ctrls['noise_magnitude'] + 3.141592653589793j * ctrls['noise_phase'])/self.block_size
        # noise_filter = torch.cat((noise_filter, noise_filter[:,-1:,:]), 1).permute(0, 2, 1)
        
        # # combtooth exciter signal
        # f0_eps = f0 + 1e-3
        # # combtooth = torch.sinc(self.sampling_rate * x / f0_eps)
        # # m = torch.floor(self.sampling_rate / f0_eps / 2.0)*2 + 1 - 2
        # # max 8 harmonics
        # smpl_rate = torch.min(self.sampling_rate, f0_eps * 8.)
        # # m = torch.floor(smpl_rate / f0_eps / 2.0)*2 + 1 - 2
        # # md = torch.where(m > 1.0, torch.remainder(smpl_rate / f0_eps, 1.0), 1.0)
        # # comb_1 = torch.sinc((self.sampling_rate - f0_eps) * x / f0_eps)
        # # combtooth = torch.lerp(comb_1, combtooth, md)
        # combtooth = torch.sinc(smpl_rate * x / f0_eps).squeeze(-1)
        
        # Dirac delta
        # note that its not accurate at boundary but fast and almost enough
        # combtooth = torch.where(x.roll(1) - x < 0., 0., 1.)
        combtooth = torch.where(x.roll(-1) - x < 0., 1., 0.)
        combtooth = combtooth.squeeze(-1)
        
        pad_mode = 'constant'
        
        combtooth_stft = torch.stft(
                            combtooth,
                            n_fft = self.win_length,
                            win_length = self.win_length,
                            hop_length = self.block_size,
                            window = self.window,
                            center = True,
                            return_complex = True,
                            # pad_mode = pad_mode)
                            pad_mode = pad_mode) * self.static_freq_minphase_wsinc.unsqueeze(-1).repeat(1, combtooth.shape[1]//self.block_size + 1)
        
        combtooth_stft = combtooth_stft * src_filter
        
        combtooth = torch.istft(
                combtooth_stft,
                n_fft = self.win_length,
                win_length = self.win_length,
                hop_length = self.block_size,
                window = self.window,
                center = True)
        
        if self.use_harmonic_env:
            harmonic_env_flat = (ctrls['harmonic_envelope_magnitude']).flatten(1)
            
            # lazy, not accurate, but fast linear interpolation
            # repeat a last sample
            harmonic_env_exp = torch.cat((harmonic_env_flat, harmonic_env_flat[:, -1:]), 1)
            # calc slopes (differentials) sample by sample, then repeat
            harmonic_env_slopes = (harmonic_env_exp[:, 1:] - harmonic_env_exp[:, :-1]).unsqueeze(-1).repeat(1, 1, self.harmonic_env_size_downsamples).flatten(1)
            # repeat indice, this is lerp coefficients
            harmonic_env_repeat_idx = (torch.arange(self.harmonic_env_size_downsamples).to(harmonic_env_flat)/self.harmonic_env_size_downsamples).unsqueeze(-1).transpose(1, 0).repeat(harmonic_env_flat.shape)
            # repeat original values, then interpolate
            harmonic_env = harmonic_env_flat.unsqueeze(-1).repeat(1, 1, self.harmonic_env_size_downsamples).flatten(1) + harmonic_env_slopes*harmonic_env_repeat_idx/self.harmonic_env_size_downsamples
            
            # # apply it to source
            combtooth *= harmonic_env
        
        # noise = self.static_noise_t.unsqueeze(0).repeat(combtooth.shape[0], combtooth.shape[1]//self.static_noise_t.shape[0] + 1)[:, :combtooth.shape[1]]
        
        # # noise_stft = torch.stft(
        # #                     noise,
        # #                     n_fft = self.win_length,
        # #                     win_length = self.win_length,
        # #                     hop_length = self.block_size,
        # #                     window = self.window,
        # #                     center = True,
        # #                     return_complex = True,
        # #                     pad_mode = pad_mode) * self.static_freq_minphase_wsinc.unsqueeze(-1).repeat(1, noise.shape[1]//self.block_size + 1)
        
        # noise_stft = torch.stft(
        #                     noise,
        #                     n_fft = self.win_length,
        #                     win_length = self.win_length,
        #                     hop_length = self.block_size,
        #                     window = self.window,
        #                     center = True,
        #                     return_complex = True,
        #                     pad_mode = pad_mode)
        
        # noise_stft = noise_stft * noise_filter
        
        # noise = torch.istft(
        #         noise_stft,
        #         n_fft = self.win_length,
        #         win_length = self.win_length,
        #         hop_length = self.block_size,
        #         window = self.window,
        #         center = True)
        
        # if self.use_noise_env:
        #     noise_env_flat = ctrls['noise_envelope_magnitude'].flatten(1)
        #     noise_env_exp = torch.cat((noise_env_flat, noise_env_flat[:, -1:]), 1)
        #     noise_env_slopes = (noise_env_exp[:, 1:] - noise_env_exp[:, :-1]).unsqueeze(-1).repeat(1, 1, self.noise_env_size_downsamples).flatten(1)
        #     noise_env_repeat_idx = (torch.arange(self.noise_env_size_downsamples).to(noise_env_flat)/self.noise_env_size_downsamples).unsqueeze(-1).transpose(1, 0).repeat(noise_env_flat.shape)
        #     noise_env = noise_env_flat.unsqueeze(-1).repeat(1, 1, self.noise_env_size_downsamples).flatten(1) + noise_env_slopes*noise_env_repeat_idx/self.noise_env_size_downsamples
        #     noise = noise * noise_env
        
        # combtooth += noise
        
        # m = 8.*2. + 1.  # harmonics of comb oscillator (harm*2+1)
        # combtooth = torch.where(x > 0., (torch.sin(m*torch.pi*x)/torch.sin(x*torch.pi)/m), torch.ones_like(x)).squeeze(-1)
        
        # signal = self.generator(ctrls['nsf_param'].transpose(2 ,1), combtooth.reshape(combtooth.shape[0], -1, self.block_size))
        signal = self.generator(ctrls['nsf_param'].transpose(2 ,1), combtooth.unsqueeze(1))
        # signal = self.generator(hidden.transpose(2 ,1), combtooth.reshape(combtooth.shape[0], -1, self.block_size).transpose(2, 1))
        # signal = self.generator(hidden.transpose(2 ,1), f0.reshape(f0.shape[0], -1, self.block_size)[:, :, 0:1].transpose(2 ,1))
        # signal = self.generator(hidden, f0.reshape(f0.shape[0], -1, self.block_size)[:, :, 0:1])
        # return signal.squeeze(1) + noise
        
        return signal.squeeze(1)