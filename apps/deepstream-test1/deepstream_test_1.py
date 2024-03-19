#!/usr/bin/env python3

################################################################################
# SPDX-FileCopyrightText: Copyright (c) 2019-2023 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################

import sys
sys.path.append('../')
import os
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst
from common.is_aarch_64 import is_aarch64
from common.bus_call import bus_call

import pyds

PGIE_CLASS_ID_VEHICLE = 0
PGIE_CLASS_ID_BICYCLE = 1
PGIE_CLASS_ID_PERSON = 2
PGIE_CLASS_ID_ROADSIGN = 3
MUXER_BATCH_TIMEOUT_USEC = 33000

def osd_sink_pad_buffer_probe(pad,info,u_data):
    frame_number=0  # 프레임 번호를 0으로 초기화
    num_rects=0   # 감지된 객체의 bounding box(경계상자)의 개수를 0으로 초기화

    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer ") 
        return  # GstBuffer를 가져올 수 없으면 함수 종료

    # gst_buffer에서 배치 메타데이터를 검색합니다.
    # pyds.gst_buffer_get_nvds_batch_meta()는
    # hash(gst_buffer)로 얻은 입력인 gst_buffer의 C 주소
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        try:
            # l_frame.data를 pyds.NvDsFrameMeta로 변환해야 한다는 점에 유의하세요.
            # 캐스팅은 pyds.NvDsFrameMeta.cast()에 의해 수행됩니다.
            # 캐스팅은 기본 메모리의 소유권도 유지합니다.
            # C 코드에서는 Python 가비지 수집기가 종료됩니다.
            # 혼자요.
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)  # l_frame.data를 pyds.NvDsFrameMeta 로 변환
        except StopIteration:
            break

        #Intiallizing object counter with 0.
        # Object Counter 초기화 (차량, 사람, 자전거, 표지판 등) 
        obj_counter = {
            PGIE_CLASS_ID_VEHICLE:0,
            PGIE_CLASS_ID_PERSON:0,
            PGIE_CLASS_ID_BICYCLE:0,
            PGIE_CLASS_ID_ROADSIGN:0
        }
        frame_number = frame_meta.frame_num  # 현재 프레임 번호 
        num_rects = frame_meta.num_obj_meta  # 감지된 객체 수 
        l_obj=frame_meta.obj_meta_list
        while l_obj is not None:
            try:
                # Casting l_obj.data to pyds.NvDsObjectMeta
                obj_meta=pyds.NvDsObjectMeta.cast(l_obj.data)  # l_obj.data를 pyds.NvDsObjectMeta로 변환
            except StopIteration:
                break
            obj_counter[obj_meta.class_id] += 1  # 감지된 객체 클래스에 따라 카운터 증가
            obj_meta.rect_params.border_color.set(0.0, 0.0, 1.0, 0.8) #0.8 is alpha (opacity), 경계상자 색상 설정 (파랑, 투명도 0.8)

            try: 
                l_obj=l_obj.next
            except StopIteration:
                break

        # 메타데이터 표시 객체 생성 (C코드에 메모리 소유권이 남아있어서 GC에 의해 해제되지 않음)
        # 디스플레이 메타 객체를 획득합니다. 메모리 소유권은 그대로 유지됩니다.
        # 다운스트림 플러그인이 계속 액세스할 수 있도록 C 코드. 그렇지 않으면
        # 이 프로브 함수가 종료되면 가비지 수집기가 이를 요청합니다.
        display_meta=pyds.nvds_acquire_display_meta_from_pool(batch_meta)
        display_meta.num_labels = 1
        py_nvosd_text_params = display_meta.text_params[0]
        # 화면에 표시될 표시 텍스트 설정
        # pyds 모듈은 문자열에 대한 버퍼를 할당하고
        # 가비지 수집기가 메모리를 요구하지 않습니다.
        # 여기에서 display_text 필드를 읽으면 해당 항목의 C 주소가 반환됩니다.
        # 할당된 문자열. 문자열 내용을 얻으려면 pyds.get_string()을 사용하십시오.
        # 화면에 표시할 텍스트 설정 
        py_nvosd_text_params.display_text = "Frame Number={} Number of Objects={} Vehicle_count={} Person_count={}".format(frame_number, num_rects, obj_counter[PGIE_CLASS_ID_VEHICLE], obj_counter[PGIE_CLASS_ID_PERSON])

        # 이제 문자열이 나타나야 하는 오프셋을 설정합니다.
        # 표시할 위치 설정 
        py_nvosd_text_params.x_offset = 10
        py_nvosd_text_params.y_offset = 12

        # Font , font-color and font-size
        py_nvosd_text_params.font_params.font_name = "Serif"
        py_nvosd_text_params.font_params.font_size = 10
        # 설정(빨간색, 녹색, 파란색, 알파); 흰색으로 설정
        py_nvosd_text_params.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)

        # Text background color
        py_nvosd_text_params.set_bg_clr = 1
        # set(red, green, blue, alpha); set to Black
        py_nvosd_text_params.text_bg_clr.set(0.0, 0.0, 0.0, 1.0)
        # pyds.get_string()을 사용하여 display_text를 문자열로 가져옵니다.
        print(pyds.get_string(py_nvosd_text_params.display_text))  # 설정된 텍스트 출력
        pyds.nvds_add_display_meta_to_frame(frame_meta, display_meta)  # 프레임에 메타데이터 추가
        try:
            l_frame=l_frame.next
        except StopIteration:
            break
			
    return Gst.PadProbeReturn.OK	


def main(args):
    # Check input arguments
    # 인수 검사
    if len(args) != 2:
      sys.stderr.write("usage: %s <media file or uri>\n" % args[0]) 
      sys.exit(1)  # 인수가 올바르지 않으면 프로그램 종료

    # Standard GStreamer initialization
    # GStreamer 초기화

    Gst.init(None)

    # gstreamer 요소 생성
    # 다른 요소의 연결을 형성할 파이프라인 요소를 생성합니다.
    # GStreamer 요소 생성
    # 요소들을 연결할 파이프라인 요소 생성
    print("Creating Pipeline \n ")
    pipeline = Gst.Pipeline()

    if not pipeline:
        sys.stderr.write(" Unable to create Pipeline \n")  # 파이프라인 생성 실패 시 에러 메시지


    # Source element for reading from the file
    # 파일에서 읽어올 Source 요소 생성
    print("Creating Source \n ")
    source = Gst.ElementFactory.make("filesrc", "file-source")
    if not source:
        sys.stderr.write(" Unable to create Source \n") # Source 요소 생성 실패 시 에러 메시지

    # Since the data format in the input file is elementary h264 stream,
    # we need a h264parser
    # 입력 파일의 데이터 형식이 H.264이므로, H.264 파서가 필요함
    print("Creating H264Parser \n")
    h264parser = Gst.ElementFactory.make("h264parse", "h264-parser")
    if not h264parser:
        sys.stderr.write(" Unable to create h264 parser \n")  # H.264 파서 생성 실패 시 에러 메시지

    # Use nvdec_h264 for hardware accelerated decode on GPU
    # GPU에서 하드웨어 가속 디코딩을 위해 nvdec_h264 사용
    print("Creating Decoder \n")
    decoder = Gst.ElementFactory.make("nvv4l2decoder", "nvv4l2-decoder")
    if not decoder:
        sys.stderr.write(" Unable to create Nvv4l2 Decoder \n") # 디코더 생성 실패 시 에러 메시지

    # Create nvstreammux instance to form batches from one or more sources.
    # 하나 이상의 소스로부터 배치(batch)를 생성하기 위한 nvstreammux 인스턴스 생성
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    if not streammux:
        sys.stderr.write(" Unable to create NvStreamMux \n")

    # nvinfer를 사용하여 디코더의 출력에 대한 추론을 실행합니다.
    # 추론 동작은 구성 파일을 통해 설정됩니다.
    # nvinfer를 사용하여 디코더의 출력에 대해 추론 수행, 추론 동작은 설정 파일로 지정
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    if not pgie:
        sys.stderr.write(" Unable to create pgie \n")

    # nvosd에서 요구하는 대로 변환기를 사용하여 NV12에서 RGBA로 변환합니다.    
    # nvosd 요소의 요구에 따라 NV12 형식의 데이터를 RGBA로 변환 
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    if not nvvidconv:
        sys.stderr.write(" Unable to create nvvidconv \n")

    # Create OSD to draw on the converted RGBA buffer
    # 변환된 RGBA 버퍼 위에 그리기 위한 OSD (On-Screen Display) 생성 
    nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")

    if not nvosd:
        sys.stderr.write(" Unable to create nvosd \n")

    # Finally render the osd output
    # OSD 출력을 최종적으로 렌더링
    if is_aarch64(): # 아키텍처 확인
        print("Creating nv3dsink \n")
        sink = Gst.ElementFactory.make("nv3dsink", "nv3d-sink")
        if not sink:
            sys.stderr.write(" Unable to create nv3dsink \n")
    else:
        print("Creating EGLSink \n")
        sink = Gst.ElementFactory.make("nveglglessink", "nvvideo-renderer")
        if not sink:
            sys.stderr.write(" Unable to create egl sink \n")

    print("Playing file %s " %args[1])
    source.set_property('location', args[1])  # Source 요소에 파일 경로 지정

    # 이 부분은 새로운 gst-nvstreammux를 사용하지 않는 경우에만 해당
    if os.environ.get('USE_NEW_NVSTREAMMUX') != 'yes': # Only set these properties if not using new gst-nvstreammux
        streammux.set_property('width', 1920)
        streammux.set_property('height', 1080)
        streammux.set_property('batched-push-timeout', MUXER_BATCH_TIMEOUT_USEC)
    
    streammux.set_property('batch-size', 1)
    pgie.set_property('config-file-path', "dstest1_pgie_config.txt") # pgie 요소 추론 설정 파일 지정

    # 파이프라인에 요소들 추가 
    print("Adding elements to Pipeline \n")
    pipeline.add(source)
    pipeline.add(h264parser)
    pipeline.add(decoder)
    pipeline.add(streammux)
    pipeline.add(pgie)
    pipeline.add(nvvidconv)
    pipeline.add(nvosd)
    pipeline.add(sink)

    # we link the elements together
    # file-source -> h264-parser -> nvh264-decoder ->
    # nvinfer -> nvvidconv -> nvosd -> video-renderer
    # 요소들을 연결함
    print("Linking elements in the Pipeline \n")
    source.link(h264parser)
    h264parser.link(decoder)

    # streammux의 "sink_0" 패드를 가져옴
    sinkpad = streammux.get_request_pad("sink_0")

    # 패드를 가져오지 못하면 에러 메시지 출력
    if not sinkpad:
        sys.stderr.write(" Unable to get the sink pad of streammux \n")

    # 디코더의 "src" 패드를 가져옴
    srcpad = decoder.get_static_pad("src")

    # 패드를 가져오지 못하면 에러 메시지 출력
    if not srcpad:
        sys.stderr.write(" Unable to get source pad of decoder \n")

    # 디코더의 "src" 패드를 streammux의 "sink_0" 패드에 연결
    srcpad.link(sinkpad)
    # streammux를 pgie에 연결
    streammux.link(pgie)
    # pgie를 nvvidconv에 연결
    pgie.link(nvvidconv)
    # nvvidconv를 nvosd에 연결
    nvvidconv.link(nvosd)
    # nvosd를 sink에 연결
    nvosd.link(sink)

    # create an event loop and feed gstreamer bus mesages to it
    # 이벤트 루프를 생성하고 여기에 gstreamer 버스 메시지를 공급합니다.
    # 이벤트 루프 생성
    loop = GLib.MainLoop()
    # 파이프라인의 bus를 가져옴
    bus = pipeline.get_bus()
    # bus에 대한 시그널 감시 시작
    bus.add_signal_watch()
    # "message" 시그널에 bus_call 함수 연결
    bus.connect ("message", bus_call, loop)

    # Lets add probe to get informed of the meta data generated, we add probe to
    # the sink pad of the osd element, since by that time, the buffer would have
    # had got all the metadata.

    # OSD 요소의 "sink" 패드에 프로브 추가
    osdsinkpad = nvosd.get_static_pad("sink")
    
    # 패드를 가져오지 못하면 에러 메시지 출력
    if not osdsinkpad:
        sys.stderr.write(" Unable to get sink pad of nvosd \n")

    # 메타데이터 생성 알림을 위한 프로브 추가
    osdsinkpad.add_probe(Gst.PadProbeType.BUFFER, osd_sink_pad_buffer_probe, 0)

    # start play back and listen to events
    # 파이프라인 실행
    print("Starting pipeline \n")
    pipeline.set_state(Gst.State.PLAYING)

    # 메인 루프 실행
    try:
        loop.run()
    except:
        pass

    # cleanup
    # 파이프라인 정리
    pipeline.set_state(Gst.State.NULL)

if __name__ == '__main__':
    sys.exit(main(sys.argv))

