"""WPF layout (XAML) for the "Stair Path" button. Every setting in stair_path.rules.DEFAULTS has a control
named after it: ``<key>_tb`` (a distance), ``<key>_cb`` (on / off); the views and clear choices are radio
buttons. Plain strings so they can be checked outside Revit.  IronPython 2.7 + CPython 3.
"""

from levelshift_ui import COLOURS

TEXT_KEYS = ("dir_x_mm", "dir_y_mm", "std_x_200", "std_y_200", "std_x_100", "std_y_100", "tag_nudge_mm",
             "tag_pad_mm", "staircase_keyword", "core_tol_mm", "level_tol_mm", "name_filter")
BOOL_KEYS = ("directional", "sweep", "room_tags", "check_dimensions", "create_types")

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

_WINDOW = '''<Window {ns}
        Title="Stair Path by Netbuild" Width="980" Height="860" MinWidth="860" MinHeight="600"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="10">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="model_tb" FontWeight="Bold" FontSize="13"/>
      <TextBlock Foreground="#555555" Margin="0,2,0,0" TextWrapping="Wrap"
                 Text="1:500 arrows only (Automatic Up/Down). 1:200 / 1:100: 'Up' (Fixed Up Direction) where a flight continues upward, 'Down' (Automatic Up/Down) where one arrives from below -- both on a through level."/>
    </StackPanel>
    <GroupBox DockPanel.Dock="Top" Margin="0,8,0,0" Header="Views">
      <StackPanel Margin="4">
        <StackPanel Orientation="Horizontal" Margin="0,2">
          <RadioButton x:Name="open_rb" GroupName="views" Content="Open plan views" VerticalAlignment="Center"
                       Margin="0,0,16,0"/>
          <RadioButton x:Name="name_rb" GroupName="views" Content="Every plan view whose name contains"
                       VerticalAlignment="Center" Margin="0,0,6,0"/>
          <TextBox x:Name="name_filter_tb" Width="200"/>
        </StackPanel>
        <StackPanel Orientation="Horizontal" Margin="0,4,0,2">
          <TextBlock Text="Clear existing stair paths in" VerticalAlignment="Center" Margin="0,0,8,0"/>
          <RadioButton x:Name="clear_views_rb" GroupName="clear" Content="these views" VerticalAlignment="Center"
                       Margin="0,0,12,0"/>
          <RadioButton x:Name="clear_model_rb" GroupName="clear" Content="the whole model" VerticalAlignment="Center"/>
        </StackPanel>
      </StackPanel>
    </GroupBox>
    <GroupBox DockPanel.Dock="Top" Margin="0,8,0,0"
              Header="Up / Down text offset (mm) -- each stair's first step is (0, 0); tune per building">
      <Grid Margin="4">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="70"/>
          <ColumnDefinition Width="Auto"/>
          <ColumnDefinition Width="70"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <CheckBox x:Name="directional_cb" Grid.Row="0" Grid.ColumnSpan="5" Margin="0,2,0,4"
                  Content="Directional: place the text away from the way each stair's first flight runs"/>
        <TextBlock Grid.Row="1" Grid.Column="0" Margin="0,3,6,3" VerticalAlignment="Center"
                   Text="Length &gt; width, run toward +X: text on the -X side by"/>
        <TextBox x:Name="dir_x_mm_tb" Grid.Row="1" Grid.Column="1" Margin="0,3" TextAlignment="Right"/>
        <TextBlock Grid.Row="1" Grid.Column="2" Grid.ColumnSpan="3" Margin="8,3" VerticalAlignment="Center"
                   Foreground="#555555" Text="(run toward -X: the standard X distance on the +X side)"/>
        <TextBlock Grid.Row="2" Grid.Column="0" Margin="0,3,6,3" VerticalAlignment="Center"
                   Text="Width &gt; length: text against the run (-Y for +Y, +Y for -Y) by"/>
        <TextBox x:Name="dir_y_mm_tb" Grid.Row="2" Grid.Column="1" Margin="0,3" TextAlignment="Right"/>
        <TextBlock Grid.Row="3" Grid.Column="0" Margin="0,3,6,3" VerticalAlignment="Center"
                   Text="Standard 1:200 -- X"/>
        <TextBox x:Name="std_x_200_tb" Grid.Row="3" Grid.Column="1" Margin="0,3" TextAlignment="Right"/>
        <TextBlock Grid.Row="3" Grid.Column="2" Margin="8,3,6,3" VerticalAlignment="Center" Text="Y"/>
        <TextBox x:Name="std_y_200_tb" Grid.Row="3" Grid.Column="3" Margin="0,3" TextAlignment="Right"/>
        <TextBlock Grid.Row="4" Grid.Column="0" Margin="0,3,6,3" VerticalAlignment="Center"
                   Text="Standard 1:100 -- X"/>
        <TextBox x:Name="std_x_100_tb" Grid.Row="4" Grid.Column="1" Margin="0,3" TextAlignment="Right"/>
        <TextBlock Grid.Row="4" Grid.Column="2" Margin="8,3,6,3" VerticalAlignment="Center" Text="Y"/>
        <TextBox x:Name="std_y_100_tb" Grid.Row="4" Grid.Column="3" Margin="0,3" TextAlignment="Right"/>
      </Grid>
    </GroupBox>
    <GroupBox DockPanel.Dock="Top" Margin="0,8,0,0" Header="Clean-up and matching">
      <StackPanel Margin="4">
        <CheckBox x:Name="sweep_cb" Margin="0,2"
                  Content="Tag every other visible stair (Automatic Up/Down, both texts) so nothing visible is left blank"/>
        <WrapPanel Margin="0,2">
          <CheckBox x:Name="room_tags_cb" VerticalAlignment="Center" Margin="0,0,6,0"
                    Content="Move room tags off the stair paths by"/>
          <TextBox x:Name="tag_nudge_mm_tb" Width="50" TextAlignment="Right"/>
          <TextBlock Text="mm (clearance" VerticalAlignment="Center" Margin="4,0"/>
          <TextBox x:Name="tag_pad_mm_tb" Width="50" TextAlignment="Right"/>
          <TextBlock Text="mm); tags of rooms named" VerticalAlignment="Center" Margin="4,0"/>
          <TextBox x:Name="staircase_keyword_tb" Width="70"/>
          <TextBlock Text="put back inside their room" VerticalAlignment="Center" Margin="4,0"/>
        </WrapPanel>
        <CheckBox x:Name="check_dimensions_cb" Margin="0,2"
                  Content="List stair paths that overlap a dimension string (nothing is moved)"/>
        <CheckBox x:Name="create_types_cb" Margin="0,2"
                  Content="Create missing 'Standard 1-500 / 1-200 / 1-100' types (duplicates of the family's 'Standard')"/>
        <WrapPanel Margin="0,2">
          <TextBlock Text="Same core within" VerticalAlignment="Center" Margin="0,0,4,0"/>
          <TextBox x:Name="core_tol_mm_tb" Width="60" TextAlignment="Right"/>
          <TextBlock Text="mm in plan.   A flight's base / top snaps to a level within" VerticalAlignment="Center"
                     Margin="4,0"/>
          <TextBox x:Name="level_tol_mm_tb" Width="50" TextAlignment="Right"/>
          <TextBlock Text="mm." VerticalAlignment="Center" Margin="4,0"/>
          <Button x:Name="defaults_btn" Content="Reset settings" Padding="8,1" Margin="16,0,0,0"/>
        </WrapPanel>
      </StackPanel>
    </GroupBox>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <Button x:Name="check_btn" Content="1. Check (plan only)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="trial_btn" Content="2. Trial run (rolls back)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="apply_btn" Content="3. Apply" Padding="10,3" Margin="0,0,20,0" FontWeight="Bold"/>
      <Button x:Name="logs_btn" Content="Open logs folder" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="about_btn" Content="About" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3"/>
    </WrapPanel>
    <TextBlock x:Name="status_tb" DockPanel.Dock="Top" Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap"/>
    <ListBox x:Name="report_lb" Margin="0,6,0,0" FontFamily="Consolas" FontSize="11"
             ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
  </DockPanel>
</Window>'''


def window_xaml():
    return _WINDOW.format(ns=_NS)


def report_lines(checks, lines):
    """[(colour, text)] for the report list: the checks (coloured by result), then the detail lines."""
    out = [(COLOURS[c.mark], str(c)) for c in checks]
    return out + [(COLOURS[""], l) for l in lines]
